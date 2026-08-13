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
 * waits (woken by inotify on /dev, so it isn't a busy-poll) and retries,
 * both at startup and whenever the endpoint goes away later (another CR52
 * reset) -- start-order independence in both directions. tap is kept
 * drained during that wait so a reset on the CR52 side doesn't also wedge
 * Linux -> CR52 traffic; frames that arrive with no endpoint to relay them
 * to are counted and dropped rather than silently lost.
 *
 * -d bypasses discovery and opens a device path directly. It exists as a
 * test seam: test-rpmsg-eth.sh points it at one end of a socat pty pair
 * standing in for the real endpoint chardev.
 *
 * usage: rpmsg-eth [-s rpmsg-eth] [-t tap0] [-d /dev/rpmsgN]
 * Bridges frames both ways until SIGTERM/SIGINT, then closes both fds,
 * logs relay counters to stderr, and exits 0 -- including when the signal
 * arrives while still waiting for the first endpoint, which is a clean
 * shutdown, not a failure.
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

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
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

/* Find the rpmsg device announcing `service`; return its dst address. */
static int find_service(const char *service, uint32_t *dst)
{
	DIR *d = opendir("/sys/bus/rpmsg/devices");
	struct dirent *e;
	char path[512], val[64];

	if (!d)
		return -1;
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

/* Create and open the char endpoint bound to `service`'s announced
 * channel. Returns the open fd, or -1 if the channel isn't announced (yet)
 * or endpoint creation failed. */
static int create_ept(const char *service)
{
	struct rpmsg_endpoint_info info;
	uint32_t dst;
	uint64_t before, after;
	char devpath[64];
	int ctrl, i;

	if (find_service(service, &dst))
		return -1;
	ctrl = open_ctrl();
	if (ctrl < 0)
		return -1;
	memset(&info, 0, sizeof(info));
	snprintf(info.name, sizeof(info.name), "%s", service);
	info.src = RPMSG_ADDR_ANY;
	info.dst = dst;
	before = eptdev_snapshot();
	if (ioctl(ctrl, RPMSG_CREATE_EPT_IOCTL, &info)) {
		close(ctrl);
		return -1;
	}
	close(ctrl);
	after = eptdev_snapshot() & ~before;
	if (!after)
		return -1;
	for (i = 0; i < 64; i++)
		if (after & (1ULL << i))
			break;
	snprintf(devpath, sizeof(devpath), "/dev/rpmsg%d", i);
	return open(devpath, O_RDWR);
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
 * the failing write()). Counts (but does not fail on) every short write. */
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
 * the CR52 comes back, but the drop must be visible rather than silent. */
static void wait_for_dev_or_tap(int inotify_fd, int tap_fd,
				 unsigned long *tap_dropped_no_endpoint)
{
	struct pollfd pfd[2] = {
		{ .fd = inotify_fd, .events = POLLIN },
		{ .fd = tap_fd, .events = POLLIN },
	};
	char ibuf[1024], fbuf[BUF_LEN];

	if (poll(pfd, 2, 1000) <= 0)
		return;
	if (pfd[0].revents & POLLIN) {
		if (read(inotify_fd, ibuf, sizeof(ibuf)) < 0 &&
		    errno != EINTR && errno != EAGAIN)
			return;
	}
	if (pfd[1].revents & POLLIN) {
		ssize_t n = read(tap_fd, fbuf, sizeof(fbuf));
		if (n > 0)
			(*tap_dropped_no_endpoint)++;
	}
}

/* Open the endpoint: `device` directly if given (test seam), else wait for
 * the CR52 to announce `service` and bind it. Retries indefinitely (until
 * a signal arrives), so the daemon is start-order independent and survives
 * the endpoint going away and coming back across a CR52 reset. tap is kept
 * drained (see wait_for_dev_or_tap) while this blocks. Returns -1 only
 * when g_stop was set (a signal arrived); callers should treat that as a
 * clean-shutdown request, not an error. */
static int open_endpoint(const char *device, const char *service, int inotify_fd,
			  int tap_fd, unsigned long *tap_dropped_no_endpoint)
{
	for (;;) {
		int fd = device ? open(device, O_RDWR) : create_ept(service);
		if (fd >= 0)
			return fd;
		if (g_stop)
			return -1;
		wait_for_dev_or_tap(inotify_fd, tap_fd, tap_dropped_no_endpoint);
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

int main(int argc, char **argv)
{
	const char *service = "rpmsg-eth", *tap_name = "tap0", *device = NULL;
	unsigned long tap_to_ept = 0, ept_to_tap = 0, dropped_oversize = 0;
	unsigned long tap_dropped_no_endpoint = 0;
	unsigned long tap_write_errors = 0, ept_write_errors = 0, short_writes = 0;
	int opt, tap, ept, inotify_fd;
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

	ept = open_endpoint(device, service, inotify_fd, tap, &tap_dropped_no_endpoint);
	if (ept < 0 && !g_stop) {
		/* open_endpoint() only gives up when g_stop is set; this is
		 * defensive, not a path we expect to hit. */
		fprintf(stderr, "rpmsg-eth: stopped waiting for endpoint\n");
		close(tap);
		close(inotify_fd);
		return 1;
	}

	/* If a signal arrived while still waiting above, ept is -1 and
	 * g_stop is set: fall straight through to the shared shutdown path
	 * below (skipping the loop) so this is exit 0, the same as a signal
	 * during the loop -- "exit 0 on clean SIGTERM" holds regardless of
	 * when the signal lands. */
	while (!g_stop && ept >= 0) {
		struct pollfd pfd[2] = {
			{ .fd = tap, .events = POLLIN },
			{ .fd = ept, .events = POLLIN },
		};
		char buf[BUF_LEN];
		ssize_t n;
		int reconnected = 0;

		if (poll(pfd, 2, -1) < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "rpmsg-eth: poll: %s\n", strerror(errno));
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
					close_ept(ept);
					ept = open_endpoint(device, service, inotify_fd,
							     tap, &tap_dropped_no_endpoint);
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
				close_ept(ept);
				ept = open_endpoint(device, service, inotify_fd,
						     tap, &tap_dropped_no_endpoint);
			}
		}
	}

	close(tap);
	close_ept(ept);
	close(inotify_fd);
	fprintf(stderr,
		"rpmsg-eth: exiting tap_to_ept=%lu ept_to_tap=%lu dropped_oversize=%lu "
		"tap_dropped_no_endpoint=%lu tap_write_errors=%lu ept_write_errors=%lu "
		"short_writes=%lu\n",
		tap_to_ept, ept_to_tap, dropped_oversize, tap_dropped_no_endpoint,
		tap_write_errors, ept_write_errors, short_writes);
	return 0;
}
