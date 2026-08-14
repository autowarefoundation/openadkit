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
 * usage: rpmsg-eth [-s rpmsg-eth] [-t tap0] [-d /dev/rpmsgN]
 * Bridges frames both ways until SIGTERM/SIGINT, then closes both fds,
 * logs relay counters to stderr, and exits 0 -- including when the signal
 * arrives while still waiting for the first endpoint, which is a clean
 * shutdown, not a failure. SIGUSR1 dumps the same counters without
 * stopping the service, for inspecting a live daemon over a serial console
 * without destroying the state you wanted to inspect. A poll() failure or
 * a fatal tap condition (see POLLERR/POLLHUP/POLLNVAL handling below) exits
 * nonzero instead, so the unit's Restart=on-failure policy actually fires
 * rather than leaving systemd thinking a broken relay exited cleanly.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
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

static volatile sig_atomic_t g_stop;
static volatile sig_atomic_t g_dump;

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
	fd = open(devpath, O_RDWR);
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

/* Write the whole buffer, retrying on a short write (a real possibility on
 * the pty the test stands the endpoint in with, and cheap insurance on the
 * real chardev too). Returns 1 on success, 0 on a hard error (errno set by
 * the failing write()). Counts (but does not fail on) every short write.
 * A write() returning exactly 0 for a nonzero-length request is treated as
 * a hard error rather than retried: it is not a short write (no progress
 * was made at all) and looping on it would spin unbounded rather than
 * making forward progress. */
static int write_full(int fd, const char *buf, size_t len, unsigned long *short_writes)
{
	size_t off = 0;

	while (off < len) {
		ssize_t w = write(fd, buf + off, len - off);
		if (w < 0) {
			if (errno == EINTR)
				continue;
			return 0;
		}
		if (w == 0) {
			errno = EIO;
			return 0;
		}
		off += (size_t)w;
		if (off < len)
			(*short_writes)++;
	}
	return 1;
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
			fd = open(device, O_RDWR);
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

int main(int argc, char **argv)
{
	const char *service = "rpmsg-eth", *tap_name = "tap0", *device = NULL;
	unsigned long tap_to_ept = 0, ept_to_tap = 0, dropped_oversize = 0;
	unsigned long tap_dropped_no_endpoint = 0;
	unsigned long tap_write_errors = 0, ept_write_errors = 0, short_writes = 0;
	int opt, tap, ept, inotify_fd, fatal_error = 0;
	struct sigaction sa;

	while ((opt = getopt(argc, argv, "s:t:d:")) != -1) {
		switch (opt) {
		case 's': service = optarg; break;
		case 't': tap_name = optarg; break;
		case 'd': device = optarg; break;
		default:
			fprintf(stderr,
				"usage: %s [-s service] [-t tap] [-d device]\n",
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
		 * it as fatal, matching the endpoint side's existing
		 * POLLERR/POLLHUP handling below. */
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
				if (write_full(ept, buf, (size_t)n, &short_writes)) {
					tap_to_ept++;
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
				if (write_full(tap, buf, (size_t)n, &short_writes)) {
					ept_to_tap++;
				} else {
					ept_write_errors++;
					fprintf(stderr,
						"rpmsg-eth: write(tap) failed: %s\n",
						strerror(errno));
				}
			} else if (n < 0 && (errno == EINTR || errno == EAGAIN)) {
				/* Transient; not a disconnect. Retry next
				 * poll iteration instead of tearing down a
				 * live endpoint. */
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
