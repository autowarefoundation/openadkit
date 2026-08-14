// SPDX-License-Identifier: Apache-2.0
/*
 * rpmsg-eth: bridges the CR52's rpmsg-eth endpoint chardev to a Linux TAP
 * device, so the kernel network stack (and CycloneDDS above it) sees an
 * ordinary Ethernet interface. One RPMsg message == one Ethernet frame in
 * both directions; the endpoint chardev is datagram-oriented, so a single
 * read() always returns exactly one frame.
 *
 * Endpoint discovery follows scripts/rpmsg-ping.c: scan
 * /sys/bus/rpmsg/devices for the channel whose `name` matches -s, read its
 * `dst`, and create the char endpoint via /dev/rpmsg_ctrl* +
 * RPMSG_CREATE_EPT_IOCTL. The CR52 announces its channel exactly once per
 * reset, so this daemon does not fail fast when the channel is absent: it
 * waits (paced by the 1s poll() timeout in wait_for_dev_or_tap(), woken
 * early by inotify on /dev when a device node changes, so it isn't a
 * busy-poll either way) and retries, both at startup and whenever the
 * endpoint goes away later (another CR52 reset) -- start-order independence
 * in both directions. tap is kept drained during that wait so a reset on
 * the CR52 side doesn't also wedge Linux -> CR52 traffic; frames that
 * arrive with no endpoint to relay them to are counted and dropped rather
 * than silently lost.
 *
 * Every retry loop iteration is logged: once on entering the wait, once on
 * the first occurrence of each distinct failure reason (with strerror()
 * where the failure has one), every ~30 retries thereafter so a stuck wait
 * is visible on a console with no scrollback, and once on every successful
 * (re)bind and every endpoint loss. A daemon that retries forever by design
 * must not be silent about it -- the observable difference between "still
 * working as designed" and "wedged" is exactly this log output.
 *
 * -d bypasses discovery and opens a device path directly. It exists as a
 * test seam: test-rpmsg-eth.sh points it at one end of a socat pty pair
 * standing in for the real endpoint chardev.
 *
 * The endpoint fd is opened O_NONBLOCK (the tap fd is not). A CR52 that
 * stops draining its vring must never be able to park this daemon inside
 * a blocking read()/write() on the endpoint -- that is exactly the board
 * defect this guards against (100% system time, zero context switches,
 * unit reporting "active (running)" forever). write_full() pairs the
 * nonblocking write with a bounded progress deadline (-T, default
 * RPMSG_ETH_EPT_PROGRESS_TIMEOUT_S) so a wedged remote is noticed and
 * treated as fatal rather than spinning silently.
 *
 * usage: rpmsg-eth [-s rpmsg-eth] [-t tap0] [-d /dev/rpmsgN] [-T seconds]
 * Bridges frames both ways until SIGTERM/SIGINT, then closes both fds,
 * logs relay counters to stderr, and exits 0 -- including when the signal
 * arrives while still waiting for the first endpoint, which is a clean
 * shutdown, not a failure. SIGUSR1 dumps the same counters without
 * stopping the service, for inspecting a live daemon over a serial console
 * without destroying the state you wanted to inspect. A poll() failure, a
 * fatal tap condition (see POLLERR/POLLHUP/POLLNVAL handling below), or the
 * endpoint making no write progress within -T seconds exits nonzero
 * instead, so the unit's Restart=on-failure policy actually fires rather
 * than leaving systemd thinking a broken relay exited cleanly.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/if.h>
#include <linux/if_tun.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

struct rpmsg_endpoint_info {
	char name[32];
	uint32_t src;
	uint32_t dst;
};
#define RPMSG_CREATE_EPT_IOCTL  _IOW(0xb5, 0x1, struct rpmsg_endpoint_info)
#define RPMSG_DESTROY_EPT_IOCTL _IO(0xb5, 0x2)
#define RPMSG_ADDR_ANY 0xFFFFFFFF

/*
 * Largest Ethernet frame this bridge will relay tap -> endpoint: netif MTU
 * 462 (frozen with the FreeRTOS side) + a 14-byte Ethernet header = 476.
 * That equals the biggest frame the CR52 side is built to accept, and it
 * sits comfortably under the 496-byte RPMsg payload budget. Anything
 * larger is dropped here rather than handed to write(): a local drop is
 * recoverable, but writing an oversize frame to the endpoint would just
 * turn into a write() failure on the other side of the same trade-off.
 * With MTU 462 enforced on the tap interface this must never trigger.
 */
#define MAX_FRAME_LEN 476
/* Read buffer: comfortably above MAX_FRAME_LEN so an oversize frame is
 * captured whole and counted, rather than silently truncated. */
#define BUF_LEN 2048

/*
 * How long write_full() tolerates the endpoint making no write progress
 * before treating it as wedged (see write_full()'s comment). The kernel's
 * own rpmsg_ctrl driver logs "timeout waiting for a tx buffer" every 15s
 * once a vring fills and nothing drains it; this must fire before that --
 * the daemon has to notice the stall itself, not just relay the kernel's
 * own warning to the console a cycle late. Overridable with -T, chiefly so
 * the test suite can use a deadline short enough to run quickly.
 */
#define RPMSG_ETH_EPT_PROGRESS_TIMEOUT_S 10

static volatile sig_atomic_t g_stop;
static volatile sig_atomic_t g_dump;
/* Set by on_ept_deadline() when write_full()'s SIGALRM backstop fires (see
 * that function). Not touched anywhere else. */
static volatile sig_atomic_t g_ept_deadline_expired;

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
}

static void on_dump_signal(int sig)
{
	(void)sig;
	g_dump = 1;
}

static void on_ept_deadline(int sig)
{
	(void)sig;
	g_ept_deadline_expired = 1;
}

/* --- rpmsg endpoint discovery: same approach as scripts/rpmsg-ping.c --- */

static int read_sysfs(const char *path, char *buf, size_t len)
{
	FILE *f = fopen(path, "r");
	if (!f)
		return -1;
	if (!fgets(buf, (int)len, f)) {
		fclose(f);
		return -1;
	}
	fclose(f);
	buf[strcspn(buf, "\n")] = '\0';
	return 0;
}

/* Find the rpmsg device announcing `service`; return its dst address.
 * `opendir_errno` is set to the errno from a failed opendir() (the rpmsg
 * bus itself isn't there -- e.g. remoteproc0 was never started), or to 0
 * when the bus exists but no channel named `service` is on it yet (the
 * ordinary "CR52 hasn't announced yet" case). Callers use this to log a
 * more specific reason than a bare "not found". */
static int find_service(const char *service, uint32_t *dst, int *opendir_errno)
{
	DIR *d = opendir("/sys/bus/rpmsg/devices");
	struct dirent *e;
	char path[512], val[64];

	*opendir_errno = 0;
	if (!d) {
		*opendir_errno = errno;
		return -1;
	}
	while ((e = readdir(d))) {
		if (e->d_name[0] == '.')
			continue;
		snprintf(path, sizeof(path),
			 "/sys/bus/rpmsg/devices/%s/name", e->d_name);
		if (read_sysfs(path, val, sizeof(val)))
			continue;
		if (strcmp(val, service))
			continue;
		snprintf(path, sizeof(path),
			 "/sys/bus/rpmsg/devices/%s/dst", e->d_name);
		if (read_sysfs(path, val, sizeof(val)))
			continue;
		*dst = (uint32_t)strtoul(val, NULL, 0);
		closedir(d);
		return 0;
	}
	closedir(d);
	return -1;
}

/* Bitmap of /dev/rpmsgN minors that exist right now (N < 64). */
static uint64_t eptdev_snapshot(void)
{
	uint64_t set = 0;
	DIR *d = opendir("/sys/class/rpmsg");
	struct dirent *e;

	if (!d)
		return 0;
	while ((e = readdir(d))) {
		unsigned n;
		if (sscanf(e->d_name, "rpmsg%u", &n) == 1 && n < 64)
			set |= 1ULL << n;
	}
	closedir(d);
	return set;
}

static int open_ctrl(void)
{
	char path[64];
	int i, fd;

	for (i = 0; i < 8; i++) {
		snprintf(path, sizeof(path), "/dev/rpmsg_ctrl%d", i);
		fd = open(path, O_RDWR);
		if (fd >= 0)
			return fd;
	}
	return -1;
}

/* The five distinct ways create_ept() can fail to bind an endpoint. Kept
 * as an enum (rather than folding everything into one -1) so the caller
 * can log a first-occurrence-per-reason message instead of one opaque
 * "still waiting" line that never says what it's waiting *on*. */
enum ept_wait_reason {
	EPT_WAIT_NO_BUS,        /* no /sys/bus/rpmsg/devices, or no channel
				 * named `service` on it yet */
	EPT_WAIT_NO_CTRL,       /* no /dev/rpmsg_ctrl* node */
	EPT_WAIT_CREATE_FAIL,   /* RPMSG_CREATE_EPT_IOCTL failed */
	EPT_WAIT_NO_EPTDEV,     /* ioctl succeeded but no new /dev/rpmsgN
				 * showed up under /sys/class/rpmsg */
	EPT_WAIT_OPEN_FAIL,     /* open() of the new eptdev failed */
};

/* Create and open the char endpoint bound to `service`'s announced
 * channel. Returns the open fd, or -1 if the channel isn't announced (yet)
 * or endpoint creation failed -- either way, *reason identifies which of
 * the five steps failed and errbuf carries a human-readable detail
 * (strerror() where the failure has an errno; a fixed string otherwise). */
static int create_ept(const char *service, enum ept_wait_reason *reason,
		       char *errbuf, size_t errbuf_len)
{
	struct rpmsg_endpoint_info info;
	uint32_t dst;
	uint64_t before, after;
	char devpath[64];
	int ctrl, fd, i, opendir_errno;

	if (find_service(service, &dst, &opendir_errno)) {
		*reason = EPT_WAIT_NO_BUS;
		if (opendir_errno)
			snprintf(errbuf, errbuf_len,
				 "opendir(/sys/bus/rpmsg/devices): %s",
				 strerror(opendir_errno));
		else
			snprintf(errbuf, errbuf_len,
				 "no channel named '%s' on the rpmsg bus yet",
				 service);
		return -1;
	}
	ctrl = open_ctrl();
	if (ctrl < 0) {
		*reason = EPT_WAIT_NO_CTRL;
		snprintf(errbuf, errbuf_len, "open(/dev/rpmsg_ctrl*): %s",
			 strerror(errno));
		return -1;
	}
	memset(&info, 0, sizeof(info));
	snprintf(info.name, sizeof(info.name), "%s", service);
	info.src = RPMSG_ADDR_ANY;
	info.dst = dst;
	before = eptdev_snapshot();
	if (ioctl(ctrl, RPMSG_CREATE_EPT_IOCTL, &info)) {
		*reason = EPT_WAIT_CREATE_FAIL;
		snprintf(errbuf, errbuf_len, "RPMSG_CREATE_EPT_IOCTL: %s",
			 strerror(errno));
		close(ctrl);
		return -1;
	}
	close(ctrl);
	after = eptdev_snapshot() & ~before;
	if (!after) {
		*reason = EPT_WAIT_NO_EPTDEV;
		snprintf(errbuf, errbuf_len,
			 "ioctl created an endpoint but no new /dev/rpmsgN appeared");
		return -1;
	}
	for (i = 0; i < 64; i++)
		if (after & (1ULL << i))
			break;
	snprintf(devpath, sizeof(devpath), "/dev/rpmsg%d", i);
	/* O_NONBLOCK: see the header comment at the top of this file and
	 * write_full()'s comment below. Without it, a CR52 that stops
	 * draining its vring parks a write() on this fd inside the kernel
	 * forever; the relay loop's read() tolerates the resulting EAGAIN
	 * the same way it already tolerates EINTR (see its comment). */
	fd = open(devpath, O_RDWR | O_NONBLOCK);
	if (fd < 0) {
		*reason = EPT_WAIT_OPEN_FAIL;
		snprintf(errbuf, errbuf_len, "open(%s): %s", devpath,
			 strerror(errno));
		/* The RPMSG_CREATE_EPT_IOCTL above already created this
		 * endpoint; failing to open it must not leak it (one
		 * eptdev leaked per retry, at 1Hz, otherwise). Destroying
		 * it needs an open fd on the eptdev itself -- there is no
		 * destroy-by-address path via the ctrl fd -- so make a
		 * best-effort read-only open purely to issue the destroy.
		 * If even that fails (e.g. the node race that produced
		 * EPT_WAIT_NO_EPTDEV, or a permissions problem so total
		 * that O_RDONLY fails too), there is genuinely no fd to
		 * destroy it with and the next retry will find it already
		 * gone or will create another; nothing further to do here. */
		fd = open(devpath, O_RDONLY);
		if (fd >= 0) {
			ioctl(fd, RPMSG_DESTROY_EPT_IOCTL);
			close(fd);
		}
		return -1;
	}
	return fd;
}

/* Tear down a char endpoint the way scripts/rpmsg-ping.c does: destroy the
 * ept explicitly before closing, rather than relying on release-time
 * teardown. Harmless (and ignored) on the -d test seam's pty, which isn't
 * an rpmsg ept and just returns ENOTTY. No-op on a negative fd. */
static void close_ept(int fd)
{
	if (fd < 0)
		return;
	ioctl(fd, RPMSG_DESTROY_EPT_IOCTL);
	close(fd);
}

static void print_counters(const char *prefix, unsigned long tap_to_ept,
			    unsigned long ept_to_tap, unsigned long dropped_oversize,
			    unsigned long tap_dropped_no_endpoint,
			    unsigned long tap_write_errors, unsigned long ept_write_errors,
			    unsigned long short_writes)
{
	fprintf(stderr,
		"rpmsg-eth: %s tap_to_ept=%lu ept_to_tap=%lu dropped_oversize=%lu "
		"tap_dropped_no_endpoint=%lu tap_write_errors=%lu ept_write_errors=%lu "
		"short_writes=%lu\n",
		prefix, tap_to_ept, ept_to_tap, dropped_oversize, tap_dropped_no_endpoint,
		tap_write_errors, ept_write_errors, short_writes);
}

/* Pointers to every relay counter, bundled so write_full() can hand them
 * straight to print_counters() when a SIGUSR1 dump lands while it is
 * retrying a write against the progress deadline (see the g_dump check in
 * write_full()'s deadline branch below). Pointers, not a value snapshot
 * taken at call time, so a dump prints the counters as they stand at the
 * moment of the signal. short_writes lives here too, rather than as its
 * own parameter (the shape write_full() used before this task): write_full()
 * is the only function that ever increments it, and it belongs in every
 * dump anyway. */
struct relay_counters {
	unsigned long *tap_to_ept;
	unsigned long *ept_to_tap;
	unsigned long *dropped_oversize;
	unsigned long *tap_dropped_no_endpoint;
	unsigned long *tap_write_errors;
	unsigned long *ept_write_errors;
	unsigned long *short_writes;
};

/* write_full()'s four-way return: WRITE_FULL_OK on success (all of `len`
 * written), 0 on a hard I/O error (errno set by the failing write()), or
 * one of these two sentinels -- kept named, not a second use of plain
 * 0/-1, so callers can't fold distinct outcomes back into one case:
 *   WRITE_FULL_DEADLINE_EXPIRED -- deadline_s > 0 and the fd made no
 *     completing write progress within that many seconds. Fatal to the
 *     caller (rebind would very likely just hit the same wedge again);
 *     that distinction from a hard I/O error is the entire point of this
 *     task.
 *   WRITE_FULL_STOPPED -- g_stop was set (a signal arrived) while this
 *     call was retrying. Not an error at all: the caller must treat it
 *     the same as a clean shutdown noticed anywhere else, not log it or
 *     count it as a failure. Exists so a SIGTERM arriving while the
 *     endpoint is wedged is not silently absorbed by the EAGAIN retry
 *     loop below until the unrelated progress deadline happens to expire
 *     -- see that loop's own g_stop check for why that gap existed. */
#define WRITE_FULL_OK (1)
#define WRITE_FULL_DEADLINE_EXPIRED (-1)
#define WRITE_FULL_STOPPED (-2)

/* Write the whole buffer, retrying on a short write (a real possibility on
 * the pty the test stands the endpoint in with, and cheap insurance on the
 * real chardev too). Counts (but does not fail on) every short write. A
 * write() returning exactly 0 for a nonzero-length request is treated as a
 * hard error rather than retried: it is not a short write (no progress was
 * made at all) and looping on it would spin unbounded rather than making
 * forward progress.
 *
 * deadline_s > 0 enables the bounded-progress path this task adds, used
 * only for writes to the rpmsg endpoint (the tap fd stays blocking and is
 * always called with deadline_s == 0, which reproduces the old behaviour
 * exactly: EAGAIN/EWOULDBLOCK can't happen on a blocking fd, and the retry
 * branch's ENOMEM case is itself gated on deadline_s > 0 (see that branch's
 * own comment for why), so that branch is simply never taken for tap
 * writes).
 *
 * counters bundles pointers to every relay counter (see its own comment):
 * short_writes is incremented directly through it, and the retry loop's
 * g_dump check hands the whole set to print_counters() so a SIGUSR1 dump
 * requested mid-stall is answered without waiting for this call to return.
 *
 * With the endpoint opened O_NONBLOCK, a CR52 that has stopped returning
 * TX buffers makes write() return EAGAIN/EWOULDBLOCK instead of blocking.
 * The old code had no such case to handle at all; the fix is not to spin
 * on it (that would just trade a blocking-syscall spin for a busy-poll
 * spin -- the board evidence was 100% *system* time, but a userspace spin
 * would show as 100% *user* time, an equally silent pegged core) but to
 * block in poll() for POLLOUT and retry, bounded by deadline_s so a
 * genuinely wedged remote is eventually reported instead of waited on
 * forever.
 *
 * The bound is enforced two ways, deliberately redundant:
 *   1. clock_gettime(CLOCK_MONOTONIC, ...) is checked before every write()
 *      attempt; once elapsed >= deadline_s this returns
 *      WRITE_FULL_DEADLINE_EXPIRED without attempting another write().
 *   2. A SIGALRM is armed for deadline_s seconds around the whole call.
 *      The clock check above only runs between syscalls, so it cannot
 *      help if write() itself is what's stuck -- the board evidence (100%
 *      system time, zero voluntary context switches) is consistent with a
 *      blocking syscall, but does not by itself prove O_NONBLOCK is
 *      honoured on this particular kernel path all the way down. SIGALRM,
 *      handled without SA_RESTART (see main()), interrupts a blocking
 *      write() or poll() with EINTR no matter which one turns out to be
 *      stuck, which hands control back to the clock check above. Cheap
 *      insurance the very next loop iteration either way: on the expected
 *      path this fires only as a wakeup for an already-EAGAIN-ing fd. */
static int write_full(int fd, const char *buf, size_t len, struct relay_counters *counters,
		       int deadline_s, double *elapsed_s_out)
{
	size_t off = 0;
	struct timespec start = { 0 };
	int have_deadline = deadline_s > 0;
	/* See the "Logged once per write_full() call" comment at the retry
	 * branch below: local (not static), so this resets every call --
	 * once per frame, not once per process. */
	int retry_logged = 0;

	if (have_deadline) {
		clock_gettime(CLOCK_MONOTONIC, &start);
		g_ept_deadline_expired = 0;
		alarm((unsigned int)deadline_s);
	}

	while (off < len) {
		ssize_t w;

		if (have_deadline) {
			struct timespec now;
			double elapsed;

			/* Checked ahead of g_stop and the deadline itself: an
			 * operator reaching for SIGUSR1 during a stall is
			 * precisely the moment a counter dump is wanted, and
			 * this loop can otherwise sit through the entire -T
			 * deadline without ever answering it -- the caller's
			 * own g_dump handling at the top of the relay loop
			 * doesn't run again until this call returns, which
			 * for a genuinely wedged endpoint is up to deadline_s
			 * seconds away. Printing it here instead, gated the
			 * same as g_stop below (only reached when
			 * have_deadline is true, which is never the case for
			 * the tap write -- EAGAIN/EWOULDBLOCK can't happen on
			 * that blocking fd, and the retry branch's ENOMEM case
			 * is separately gated on have_deadline too, see that
			 * branch's own comment -- so the tap write cannot be
			 * sitting in this retry loop at all), keeps the dump
			 * within this loop's own 1s poll() bound (see below)
			 * instead of the -T one.
			 * Checked before g_stop, not after, so a dump pending
			 * at the same moment as a stop still prints: once
			 * WRITE_FULL_STOPPED is returned below, the caller
			 * breaks out of the relay loop without ever reaching
			 * its own top-of-loop g_dump check again. This does
			 * not change g_stop's own precedence -- it still
			 * takes priority over waiting out the deadline, and a
			 * dump here can add at most one fprintf() before that
			 * check runs, not a wait of any length. */
			if (g_dump) {
				g_dump = 0;
				print_counters("counters", *counters->tap_to_ept,
						*counters->ept_to_tap,
						*counters->dropped_oversize,
						*counters->tap_dropped_no_endpoint,
						*counters->tap_write_errors,
						*counters->ept_write_errors,
						*counters->short_writes);
			}

			/* Checked ahead of the deadline itself: a clean stop
			 * takes priority over a wedge report, and must not
			 * wait out however much of the deadline is left. Only
			 * gated on have_deadline (i.e. only for the endpoint
			 * write, never the tap write, which stays a plain
			 * blocking fd and cannot be sitting in this retry
			 * loop at all) -- see this sentinel's own comment
			 * above for why. */
			if (g_stop) {
				alarm(0);
				errno = EINTR;
				return WRITE_FULL_STOPPED;
			}

			clock_gettime(CLOCK_MONOTONIC, &now);
			elapsed = (double)(now.tv_sec - start.tv_sec) +
				  (double)(now.tv_nsec - start.tv_nsec) / 1e9;
			if (g_ept_deadline_expired || elapsed >= (double)deadline_s) {
				alarm(0);
				if (elapsed_s_out)
					*elapsed_s_out = elapsed;
				errno = ETIMEDOUT;
				return WRITE_FULL_DEADLINE_EXPIRED;
			}
		}

		w = write(fd, buf + off, len - off);
		if (w < 0) {
			/* ENOMEM is treated the same as EAGAIN/EWOULDBLOCK,
			 * not the hard-error path below: upstream
			 * rpmsg_char.c's rpmsg_trysendto() maps a full TX
			 * vring's -ENOMEM to -EAGAIN, but only inside the
			 * `filp->f_flags & O_NONBLOCK` branch -- exactly the
			 * branch this ept fd takes (see O_NONBLOCK's own
			 * comment where the fd is opened). This board does
			 * not run that upstream kernel -- it runs an R-Car
			 * BSP kernel, and this project has already recorded
			 * elsewhere that the CI kernel is not the board
			 * kernel. If that remap is absent, backported
			 * differently, or simply patched out on this vendor
			 * tree, a full vring surfaces here as a bare ENOMEM
			 * instead of EAGAIN. Without this line, write_full()
			 * would take the hard-error path below, count it as
			 * a real write failure, and rebind -- silently
			 * disabling the entire progress-deadline mechanism
			 * this file exists to add, on the one kernel it has
			 * to actually work on. The test suite cannot catch
			 * that regression: the pty this daemon is tested
			 * against always returns plain EAGAIN and has no way
			 * to produce ENOMEM instead. Same class of
			 * not-betting-on-an-unverified-kernel-behaviour as
			 * the SIGALRM backstop in this function's own
			 * comment above; it just was not applied to this
			 * errno too.
			 *
			 * `&& have_deadline` is load-bearing, not decoration:
			 * unlike EAGAIN/EWOULDBLOCK (which genuinely cannot
			 * happen on a blocking fd), ENOMEM has nothing to do
			 * with readiness -- the tun/tap write path can return
			 * it on plain skb allocation failure under memory
			 * pressure, independent of whether the fd would block.
			 * An earlier version of this fix accepted ENOMEM
			 * unconditionally, which reached the tap write too
			 * (deadline_s == 0): poll(POLLOUT) cannot wait for an
			 * allocator condition -- tun reports POLLOUT from
			 * link/socket-writability, not allocator health -- so
			 * it returns ready immediately and the loop re-writes
			 * at once, with no alarm, no clock check and no g_stop
			 * check (all three are gated on have_deadline, further
			 * below), reproducing this exact family's original
			 * defect -- an unbounded, SIGTERM-deaf spin -- on the
			 * tap fd instead of the endpoint. Gating on
			 * have_deadline keeps a bare ENOMEM on the tap write
			 * exactly where it was before this fix: the hard-error
			 * path, a counted, logged, recoverable rebind. */
			if (errno == EAGAIN || errno == EWOULDBLOCK ||
			    (errno == ENOMEM && have_deadline)) {
				struct pollfd pfd = { .fd = fd, .events = POLLOUT };

				/* Logged once per write_full() call (one call
				 * == one frame), the first time that frame's
				 * write has to retry -- not every poll() cycle,
				 * which would otherwise flood the console for
				 * the entire length of a genuine wedge. This is
				 * the only place a stall becomes visible before
				 * either the progress deadline or a SIGUSR1 dump
				 * fires, and it answers a question the CI seam
				 * cannot: strerror(errno) here names ENOMEM
				 * specifically when the vendor kernel's
				 * TX-vring-full path above is what is actually
				 * being hit on the board, versus the ordinary
				 * EAGAIN/EWOULDBLOCK a pty always produces.
				 * test-rpmsg-eth.sh's SIGUSR1-during-a-stall case
				 * also waits on this line rather than guessing at
				 * buffer-fill timing with a fixed sleep. */
				if (!retry_logged) {
					retry_logged = 1;
					fprintf(stderr,
						"rpmsg-eth: write(fd=%d) not ready (%s), "
						"retrying\n",
						fd, strerror(errno));
				}

				/* Bounded: 1s when a deadline applies (so the
				 * clock is rechecked periodically even if the
				 * SIGALRM above were somehow lost, rather than
				 * trusting a single mechanism), or the classic
				 * unbounded wait when it doesn't (tap writes;
				 * matches the pre-O_NONBLOCK behaviour, which
				 * never spun -- it blocked in write() itself).
				 * Either way this always blocks in poll();
				 * never busy-retries. */
				poll(&pfd, 1, have_deadline ? 1000 : -1);
				continue;
			}
			if (errno == EINTR)
				continue;
			if (have_deadline)
				alarm(0);
			return 0;
		}
		if (w == 0) {
			if (have_deadline)
				alarm(0);
			errno = EIO;
			return 0;
		}
		off += (size_t)w;
		if (off < len)
			(*counters->short_writes)++;
	}
	if (have_deadline)
		alarm(0);
	return WRITE_FULL_OK;
}

/* Block up to 1s waiting for either a /dev change (a pending endpoint
 * discovery/reconnect) or a frame arriving on tap while there is no
 * endpoint to relay it to. tap frames seen here are counted via
 * *tap_dropped_no_endpoint and dropped: there is nowhere to put them until
 * the CR52 comes back, but the drop must be visible rather than silent.
 * This 1s poll() timeout, not the inotify watch, is what paces the retry
 * loop at roughly 1Hz: inotify only wakes it early when a device node
 * actually changes under /dev, and a channel announcement need not create
 * anything there at all (the new node appears under /sys/class/rpmsg,
 * which this function does not watch).
 *
 * Returns 1 if the tap fd reported POLLERR/POLLHUP/POLLNVAL -- the same
 * fatal condition the steady-state relay loop below treats as fatal, and
 * for the same reason: POLLERR is delivered regardless of requested
 * events and latches once the tap stops being a live, registered
 * netdevice (e.g. `ip link del tap0` under the daemon), so poll() would
 * otherwise return immediately, forever, instead of waiting out its 1s
 * timeout. That defeats the ~1Hz retry pacing this function exists to
 * provide and turns the endpoint wait into a full-speed busy loop instead
 * of a silent hang. Returns 0 otherwise (the ordinary 1s timeout, an
 * inotify wakeup, or a tap frame drained above). The caller must treat a
 * 1 as fatal and stop retrying -- there is no timeout left to pace a
 * retry against once the tap fd itself is broken. */
static int wait_for_dev_or_tap(int inotify_fd, int tap_fd, const char *tap_name,
				unsigned long *tap_dropped_no_endpoint)
{
	struct pollfd pfd[2] = {
		{ .fd = inotify_fd, .events = POLLIN },
		{ .fd = tap_fd, .events = POLLIN },
	};
	char ibuf[1024], fbuf[BUF_LEN];

	if (poll(pfd, 2, 1000) <= 0)
		return 0;

	if (pfd[1].revents & (POLLERR | POLLHUP | POLLNVAL)) {
		fprintf(stderr,
			"rpmsg-eth: tap %s reported a fatal poll condition "
			"(POLLERR=%d POLLHUP=%d POLLNVAL=%d) while waiting "
			"for the endpoint -- exiting so the service manager "
			"can restart us\n",
			tap_name,
			!!(pfd[1].revents & POLLERR),
			!!(pfd[1].revents & POLLHUP),
			!!(pfd[1].revents & POLLNVAL));
		return 1;
	}

	if (pfd[0].revents & POLLIN) {
		if (read(inotify_fd, ibuf, sizeof(ibuf)) < 0 &&
		    errno != EINTR && errno != EAGAIN)
			return 0;
	}
	if (pfd[1].revents & POLLIN) {
		ssize_t n = read(tap_fd, fbuf, sizeof(fbuf));
		if (n > 0)
			(*tap_dropped_no_endpoint)++;
	}
	return 0;
}

static const char *ept_wait_reason_str(enum ept_wait_reason reason)
{
	switch (reason) {
	case EPT_WAIT_NO_BUS:      return "no rpmsg bus / channel not announced";
	case EPT_WAIT_NO_CTRL:     return "no /dev/rpmsg_ctrl* node";
	case EPT_WAIT_CREATE_FAIL: return "endpoint creation ioctl failed";
	case EPT_WAIT_NO_EPTDEV:   return "no new eptdev appeared";
	case EPT_WAIT_OPEN_FAIL:   return "open() of the new eptdev failed";
	}
	return "unknown";
}

/* open_endpoint()'s two ways of giving up without a bound endpoint. Kept
 * as named negative sentinels, not a bare -1, precisely so a fatal tap
 * condition can no longer be conflated with a clean-shutdown signal --
 * that conflation was the bug this fixes. */
#define OPEN_ENDPOINT_STOPPED   (-1)
#define OPEN_ENDPOINT_TAP_FATAL (-2)

/* Open the endpoint: `device` directly if given (test seam), else wait for
 * the CR52 to announce `service` and bind it. Retries indefinitely (until
 * a signal arrives or the tap fd hits a fatal condition), so the daemon is
 * start-order independent and survives the endpoint going away and coming
 * back across a CR52 reset. tap is kept drained (see wait_for_dev_or_tap)
 * while this blocks.
 *
 * Returns the open fd (>= 0) on success, or one of two negative sentinels
 * on giving up -- these must not be conflated, since only one of them is a
 * clean shutdown:
 *   OPEN_ENDPOINT_STOPPED    -- g_stop was set (a signal arrived); callers
 *                                should treat this as a clean-shutdown
 *                                request, not an error.
 *   OPEN_ENDPOINT_TAP_FATAL  -- wait_for_dev_or_tap() saw POLLERR/POLLHUP/
 *                                POLLNVAL on the tap fd (already logged
 *                                there); callers must exit nonzero, the
 *                                same as the steady-state relay loop's
 *                                handling of the identical condition.
 *
 * Logs once on entering the wait (naming what is being waited for), once
 * on the first occurrence of each distinct failure reason, every ~30
 * retries thereafter regardless of reason (so a wait stuck on the same
 * reason for minutes still produces console output), and once on every
 * successful bind. A silent 1Hz-forever retry is indistinguishable from a
 * hang on a serial console with no way to inspect process state; these
 * lines are the only thing that tells the two apart. */
static int open_endpoint(const char *device, const char *service, int inotify_fd,
			  int tap_fd, const char *tap_name,
			  unsigned long *tap_dropped_no_endpoint)
{
	unsigned long attempt = 0;
	int have_last_reason = 0;
	enum ept_wait_reason last_reason = EPT_WAIT_NO_BUS;

	fprintf(stderr, "rpmsg-eth: waiting for endpoint (%s)...\n",
		device ? device : service);

	for (;;) {
		enum ept_wait_reason reason = EPT_WAIT_NO_BUS;
		char errbuf[160];
		int fd;

		errbuf[0] = '\0';
		if (device) {
			/* O_NONBLOCK for the same reason as create_ept()'s
			 * real-endpoint open above: this -d path is the test
			 * seam, and the test's mock endpoint stands in for a
			 * CR52 that can wedge exactly the same way. */
			fd = open(device, O_RDWR | O_NONBLOCK);
			if (fd < 0)
				snprintf(errbuf, sizeof(errbuf), "open(%s): %s",
					 device, strerror(errno));
		} else {
			fd = create_ept(service, &reason, errbuf, sizeof(errbuf));
		}

		if (fd >= 0) {
			fprintf(stderr, "rpmsg-eth: endpoint bound (%s)\n",
				device ? device : service);
			return fd;
		}
		if (g_stop)
			return OPEN_ENDPOINT_STOPPED;

		attempt++;
		if (!have_last_reason || reason != last_reason ||
		    attempt % 30 == 0) {
			fprintf(stderr,
				"rpmsg-eth: still waiting for endpoint after %lu attempt(s): %s\n",
				attempt,
				errbuf[0] ? errbuf : ept_wait_reason_str(reason));
			last_reason = reason;
			have_last_reason = 1;
		}
		if (wait_for_dev_or_tap(inotify_fd, tap_fd, tap_name,
					 tap_dropped_no_endpoint))
			return OPEN_ENDPOINT_TAP_FATAL;
	}
}

static int tap_open(const char *name)
{
	struct ifreq ifr;
	int fd = open("/dev/net/tun", O_RDWR);

	if (fd < 0)
		return -1;
	memset(&ifr, 0, sizeof(ifr));
	ifr.ifr_flags = IFF_TAP | IFF_NO_PI;
	snprintf(ifr.ifr_name, sizeof(ifr.ifr_name), "%s", name);
	if (ioctl(fd, TUNSETIFF, &ifr)) {
		close(fd);
		return -1;
	}
	return fd;
}

/* Parse -T's argument: a strictly positive base-10 integer count of
 * seconds. Rejects <= 0 and anything non-numeric (trailing garbage,
 * empty string, overflow) -- a silently-clamped or silently-zero deadline
 * would either never fire or fire immediately, both worse than refusing
 * to start. Returns 0 and fills *out on success, -1 on a bad value. */
static int parse_positive_seconds(const char *s, int *out)
{
	char *end;
	long v;

	errno = 0;
	v = strtol(s, &end, 10);
	if (end == s || *end != '\0' || errno == ERANGE || v <= 0 || v > INT_MAX)
		return -1;
	*out = (int)v;
	return 0;
}

int main(int argc, char **argv)
{
	const char *service = "rpmsg-eth", *tap_name = "tap0", *device = NULL;
	unsigned long tap_to_ept = 0, ept_to_tap = 0, dropped_oversize = 0;
	unsigned long tap_dropped_no_endpoint = 0;
	unsigned long tap_write_errors = 0, ept_write_errors = 0, short_writes = 0;
	/* See struct relay_counters's own comment: this is what lets
	 * write_full() answer a SIGUSR1 dump itself while retrying a write
	 * against the progress deadline, instead of only at the top of the
	 * relay loop below. */
	struct relay_counters counters = {
		.tap_to_ept = &tap_to_ept,
		.ept_to_tap = &ept_to_tap,
		.dropped_oversize = &dropped_oversize,
		.tap_dropped_no_endpoint = &tap_dropped_no_endpoint,
		.tap_write_errors = &tap_write_errors,
		.ept_write_errors = &ept_write_errors,
		.short_writes = &short_writes,
	};
	int ept_progress_timeout_s = RPMSG_ETH_EPT_PROGRESS_TIMEOUT_S;
	int opt, tap, ept, inotify_fd, fatal_error = 0;
	struct sigaction sa;

	while ((opt = getopt(argc, argv, "s:t:d:T:")) != -1) {
		switch (opt) {
		case 's': service = optarg; break;
		case 't': tap_name = optarg; break;
		case 'd': device = optarg; break;
		case 'T':
			if (parse_positive_seconds(optarg, &ept_progress_timeout_s)) {
				fprintf(stderr,
					"rpmsg-eth: invalid -T value '%s': must be a "
					"positive integer number of seconds\n",
					optarg);
				return 1;
			}
			break;
		default:
			fprintf(stderr,
				"usage: %s [-s service] [-t tap] [-d device] [-T seconds]\n",
				argv[0]);
			return 1;
		}
	}

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_signal;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_dump_signal;
	sigaction(SIGUSR1, &sa, NULL);

	/* No SA_RESTART (sa.sa_flags is 0 from the memset above, same as the
	 * other handlers): write_full()'s progress-deadline backstop relies
	 * on this SIGALRM interrupting a blocking write()/poll() with EINTR
	 * rather than transparently resuming it -- see write_full()'s
	 * comment. */
	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_ept_deadline;
	sigaction(SIGALRM, &sa, NULL);

	inotify_fd = inotify_init1(IN_NONBLOCK);
	if (inotify_fd < 0) {
		fprintf(stderr, "rpmsg-eth: inotify_init1: %s\n", strerror(errno));
		return 1;
	}
	if (inotify_add_watch(inotify_fd, "/dev", IN_CREATE) < 0) {
		fprintf(stderr, "rpmsg-eth: inotify_add_watch(/dev): %s\n",
			strerror(errno));
		return 1;
	}

	tap = tap_open(tap_name);
	if (tap < 0) {
		fprintf(stderr, "rpmsg-eth: tap_open(%s): %s\n", tap_name,
			strerror(errno));
		return 1;
	}

	ept = open_endpoint(device, service, inotify_fd, tap, tap_name,
			     &tap_dropped_no_endpoint);
	if (ept == OPEN_ENDPOINT_TAP_FATAL) {
		fatal_error = 1;
	} else if (ept < 0 && !g_stop) {
		/* open_endpoint() only gives up when g_stop is set or the
		 * tap fd hit a fatal condition (OPEN_ENDPOINT_TAP_FATAL,
		 * handled above); this remaining branch is defensive, not a
		 * path we expect to hit. */
		fprintf(stderr, "rpmsg-eth: stopped waiting for endpoint\n");
		fatal_error = 1;
	}

	/* If we are giving up here -- g_stop was set, or the tap fd hit a
	 * fatal condition above -- ept is negative, so the while loop below
	 * never runs and this falls straight through to the shared shutdown
	 * path at the bottom, which returns fatal_error ? 1 : 0. That keeps
	 * "exit 0 on a clean SIGTERM" true regardless of when the signal
	 * lands, while a fatal tap condition still exits nonzero, exactly
	 * like the steady-state relay loop's handling of the identical
	 * condition. Otherwise both fds are open and we are about to enter
	 * the poll loop: print a readiness marker so a caller
	 * (test-rpmsg-eth.sh, under QEMU TCG in CI, cannot assume a fixed
	 * startup latency) can wait on it instead of guessing. */
	if (ept >= 0)
		fprintf(stderr, "rpmsg-eth: ready\n");

	while (!g_stop && ept >= 0) {
		struct pollfd pfd[2] = {
			{ .fd = tap, .events = POLLIN },
			{ .fd = ept, .events = POLLIN },
		};
		char buf[BUF_LEN];
		ssize_t n;
		int reconnected = 0;

		if (g_dump) {
			g_dump = 0;
			print_counters("counters", tap_to_ept, ept_to_tap, dropped_oversize,
					tap_dropped_no_endpoint, tap_write_errors,
					ept_write_errors, short_writes);
		}

		if (poll(pfd, 2, -1) < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "rpmsg-eth: poll: %s\n", strerror(errno));
			fatal_error = 1;
			break;
		}

		/* POLLERR is delivered regardless of requested events, and
		 * tun_chr_poll() returns it once the tun device this fd
		 * refers to stops being a live, registered netdevice --
		 * which is exactly what `ip link del tap0` does to a
		 * persistent tap the daemon still holds open (confirmed
		 * against the 6.1 tun.c: tun_get() failing, or
		 * dev->reg_state != NETREG_REGISTERED, both return
		 * EPOLLERR). Without this check the loop would spin on a
		 * dead tap forever -- POLLIN never sets again, but poll()
		 * keeps returning immediately with POLLERR set and nothing
		 * read, sleeps, logs or exits -- a pegged core and a dead
		 * link while the unit still reads "active (running)". Treat
		 * it as fatal: unlike the endpoint side (which funnels
		 * POLLERR/POLLHUP into a read() and lets the read's result
		 * decide -- see that branch's own EAGAIN-plus-latched-flags
		 * handling below), tap has no rebind path to fall back to,
		 * so there is nothing productive left to retry into. */
		if (pfd[0].revents & (POLLERR | POLLHUP | POLLNVAL)) {
			fprintf(stderr,
				"rpmsg-eth: tap %s reported a fatal poll condition "
				"(POLLERR=%d POLLHUP=%d POLLNVAL=%d) -- exiting so the "
				"service manager can restart us\n",
				tap_name,
				!!(pfd[0].revents & POLLERR),
				!!(pfd[0].revents & POLLHUP),
				!!(pfd[0].revents & POLLNVAL));
			fatal_error = 1;
			break;
		}

		if (pfd[0].revents & POLLIN) {
			n = read(tap, buf, sizeof(buf));
			if (n > MAX_FRAME_LEN) {
				dropped_oversize++;
			} else if (n > 0) {
				double stalled_s = 0;
				int wr = write_full(ept, buf, (size_t)n, &counters,
						     ept_progress_timeout_s, &stalled_s);

				if (wr == WRITE_FULL_OK) {
					tap_to_ept++;
				} else if (wr == WRITE_FULL_DEADLINE_EXPIRED) {
					/* The endpoint took the whole
					 * progress deadline without accepting
					 * this frame -- a wedged CR52, the
					 * defect this task exists to catch.
					 * Fatal, not a rebind: unlike EOF/a
					 * write error, nothing here tells us
					 * the CR52 is gone and a fresh
					 * endpoint would help: create_ept()
					 * would very likely just bind the
					 * same wedged channel again. Exiting
					 * lets systemd apply its restart
					 * policy and back off / alert instead
					 * of this daemon silently retrying
					 * into the same wall. */
					fprintf(stderr,
						"rpmsg-eth: endpoint %s did not finish "
						"writing a frame within %.1fs (deadline "
						"%ds) -- treating as wedged and exiting "
						"so the service manager can restart us\n",
						device ? device : service, stalled_s,
						ept_progress_timeout_s);
					fatal_error = 1;
					/* No print_counters() call here: the
					 * shared shutdown path at the bottom
					 * of main() prints them once this
					 * break falls through to it. Printing
					 * them here too would put the same
					 * line on a slow serial console twice
					 * during exactly the incident someone
					 * is reading it to diagnose. */
					break;
				} else if (wr == WRITE_FULL_STOPPED) {
					/* g_stop was set while this write was
					 * retrying (e.g. SIGTERM arrived while
					 * the endpoint was wedged). Not an
					 * error and not logged as one: fall out
					 * of the relay loop the same way a
					 * SIGTERM arriving between poll()
					 * iterations already does, so a clean
					 * stop still exits 0 through the single
					 * exit path at the bottom of main(). */
					break;
				} else {
					tap_write_errors++;
					fprintf(stderr,
						"rpmsg-eth: write(ept) failed: %s\n",
						strerror(errno));
					/* A write error on the endpoint is as
					 * good a signal as a read EOF that the
					 * CR52 is gone: rebind now instead of
					 * waiting for the read side to notice.
					 * pfd[1].revents below described the
					 * *old* ept fd, so it must not be
					 * consulted against the new one. */
					fprintf(stderr,
						"rpmsg-eth: endpoint lost (write failed), rebinding\n");
					close_ept(ept);
					ept = open_endpoint(device, service, inotify_fd,
							     tap, tap_name,
							     &tap_dropped_no_endpoint);
					if (ept == OPEN_ENDPOINT_TAP_FATAL)
						fatal_error = 1;
					reconnected = 1;
				}
			}
		}

		if (!reconnected && ept >= 0 &&
		    (pfd[1].revents & (POLLIN | POLLHUP | POLLERR))) {
			n = read(ept, buf, sizeof(buf));
			if (n > 0) {
				/* No deadline on this write: it targets tap,
				 * which stays a blocking fd (see tap_open()),
				 * so write_full() never sees EAGAIN/EWOULDBLOCK
				 * here, and its ENOMEM case is itself gated on
				 * deadline_s > 0 (see write_full()'s retry
				 * branch), so this call behaves exactly as it
				 * always has. */
				if (write_full(tap, buf, (size_t)n, &counters, 0, NULL) ==
				    WRITE_FULL_OK) {
					ept_to_tap++;
				} else {
					ept_write_errors++;
					fprintf(stderr,
						"rpmsg-eth: write(tap) failed: %s\n",
						strerror(errno));
				}
			} else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) &&
				   (pfd[1].revents & (POLLHUP | POLLERR))) {
				/* EAGAIN alone (the branch below) would be an
				 * ordinary spurious/raced wakeup, safe to just
				 * retry next poll(). But POLLHUP/POLLERR having
				 * *also* latched on this fd means poll() will
				 * keep reporting them on every following call
				 * regardless of whether there is ever anything
				 * to read -- with the endpoint's old blocking
				 * fd that combination could not reach here at
				 * all (the read would have delivered whatever
				 * made those flags true instead of EAGAIN), but
				 * O_NONBLOCK opens up exactly this gap: falling
				 * into the plain-transient branch below would
				 * return to poll(pfd, 2, -1) above, which
				 * reports the same still-latched revents
				 * immediately, forever -- an unbounded busy
				 * loop (100% user time this time, not the
				 * system time the board saw, but an equally
				 * silent pegged core) on the very fd this task
				 * exists to stop spinning on. Upstream
				 * rpmsg_char is not known to produce this
				 * combination (a destroyed ept gives EPIPE, a
				 * hung-up chardev gives EIO or a 0-byte read,
				 * both already handled by the branch further
				 * below), but this daemon runs against a
				 * vendor kernel, and betting a busy-loop on
				 * that mapping holding is exactly the kind of
				 * assumption write_full()'s SIGALRM backstop
				 * exists to not make. Treat it the same as the
				 * EOF/read-error branch further below: rebind
				 * rather than trust the read side to notice on
				 * its own. */
				fprintf(stderr,
					"rpmsg-eth: endpoint lost (EAGAIN with a latched "
					"fatal poll condition), rebinding\n");
				close_ept(ept);
				ept = open_endpoint(device, service, inotify_fd,
						     tap, tap_name,
						     &tap_dropped_no_endpoint);
				if (ept == OPEN_ENDPOINT_TAP_FATAL)
					fatal_error = 1;
			} else if (n < 0 && (errno == EINTR || errno == EAGAIN ||
					      errno == EWOULDBLOCK)) {
				/* Transient; not a disconnect. EAGAIN/
				 * EWOULDBLOCK is expected now that the
				 * endpoint is O_NONBLOCK: a POLLIN wakeup can
				 * still race another consumer or be spurious.
				 * Retry next poll iteration instead of
				 * tearing down a live endpoint or counting
				 * this as an error. (The POLLHUP/POLLERR
				 * variant of this is handled separately above
				 * -- it must not fall through to here.) */
			} else {
				/* n == 0 (EOF) or a genuine read error:
				 * CR52 reset. Rebind and keep going rather
				 * than exiting. */
				fprintf(stderr,
					"rpmsg-eth: endpoint lost (EOF/read error), rebinding\n");
				close_ept(ept);
				ept = open_endpoint(device, service, inotify_fd,
						     tap, tap_name,
						     &tap_dropped_no_endpoint);
				if (ept == OPEN_ENDPOINT_TAP_FATAL)
					fatal_error = 1;
			}
		}
	}

	close(tap);
	close_ept(ept);
	close(inotify_fd);
	print_counters("exiting", tap_to_ept, ept_to_tap, dropped_oversize,
			tap_dropped_no_endpoint, tap_write_errors, ept_write_errors,
			short_writes);
	return fatal_error ? 1 : 0;
}
