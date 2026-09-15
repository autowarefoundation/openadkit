// SPDX-License-Identifier: Apache-2.0
/*
 * rpmsg-ping: RPMsg round-trip tester over the rpmsg_char uAPI.
 *
 * Scans /sys/bus/rpmsg/devices for the device whose `name` matches -s,
 * reads its announced `dst` address, creates a char endpoint through
 * /dev/rpmsg_ctrl*, then write()s sequenced payloads and checks the reply
 * to each one. Static-linked so the same binary runs on both the BSP Yocto
 * rootfs and the AutoSD NFS rootfs.
 *
 * Two remote protocols exist, so the reply check has two modes:
 *
 *   responder (default) -- the remote answers every request with the same
 *       constant string. This is what the vendor CR52 firmware does: it
 *       logs "Incoming msg: <our payload>" on its own console and replies
 *       "Hello world from CR52/Free-RTOS!". Verified per request: a reply
 *       arrives, is non-empty, and is byte-identical to the first one, so
 *       a corrupted or mis-sequenced vring still fails the run.
 *
 *   echo (-e) -- the remote returns the request verbatim; each reply's
 *       leading bytes must match what was sent (a prefix compare, not a
 *       full-length match).
 *
 *   listen (-l <seconds>) -- for the Safety Island channel "rpmsg-si". Sends
 *       "hello\n" once so the CR52 learns this endpoint's address (OpenAMP
 *       latches dest_addr on the first inbound frame), then prints every
 *       newline-terminated line it receives as "RPMSG_SI_RX <line>". SIGUSR1
 *       writes "fault=1\n", SIGUSR2 writes "fault=0\n". 0 seconds = until
 *       SIGTERM/SIGINT. Ends with RPMSG_LISTEN_PASS n=<hb> gaps=0 when the
 *       heartbeat seq values were consecutive and at least seconds-2 arrived.
 *       -d <dev> opens an endpoint device (or a pty in the unit test) directly
 *       instead of discovering the service, the same seam rpmsg-eth.c has.
 *
 * Exit 0 + "RPMSG_PING_PASS n=<count>" on success; exit 1 + a
 * "RPMSG_PING_FAIL reason=..." line on any failure.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

static volatile sig_atomic_t g_fault_req;   /* 1 = set, 2 = clear */
static volatile sig_atomic_t g_stop;
static void on_usr1(int s) { (void)s; g_fault_req = 1; }
static void on_usr2(int s) { (void)s; g_fault_req = 2; }
static void on_term(int s) { (void)s; g_stop = 1; }

/*
 * Listens on an already-open endpoint for the rpmsg-si heartbeat. Writes
 * "hello\n" up front, then "fault=1\n" / "fault=0\n" on SIGUSR1 / SIGUSR2,
 * and logs every newline-terminated line the CR52 sends.
 */
static int listen_loop(int ept, int seconds)
{
	char acc[512]; size_t used = 0;
	long n_hb = 0, gaps = 0, last_seq = -1;
	time_t t_end = time(NULL) + seconds;

	signal(SIGUSR1, on_usr1); signal(SIGUSR2, on_usr2);
	signal(SIGTERM, on_term); signal(SIGINT, on_term);
	if (write(ept, "hello\n", 6) != 6) {
		printf("RPMSG_LISTEN_FAIL reason=hello_write errno=%d\n", errno);
		return 1;
	}
	while (!g_stop && (seconds == 0 || time(NULL) < t_end)) {
		struct pollfd pfd = { .fd = ept, .events = POLLIN };
		if (g_fault_req) {
			const char *msg = g_fault_req == 1 ? "fault=1" : "fault=0";
			const char *wire = g_fault_req == 1 ? "fault=1\n" : "fault=0\n";
			g_fault_req = 0;
			if (write(ept, wire, strlen(wire)) < 0)
				printf("RPMSG_SI_TX_FAIL %s errno=%d\n", msg, errno);
			else
				printf("RPMSG_SI_TX %s\n", msg);
			fflush(stdout);
		}
		int pr = poll(&pfd, 1, 200);
		if (pr <= 0) continue;
		if (pfd.revents & (POLLERR | POLLHUP)) {
			printf("RPMSG_LISTEN_FAIL reason=channel_closed n=%ld\n", n_hb);
			return 1;
		}
		ssize_t r = read(ept, acc + used, sizeof(acc) - 1 - used);
		if (r <= 0) continue;
		used += (size_t)r; acc[used] = '\0';
		char *line = acc, *nl;
		while ((nl = memchr(line, '\n', used - (size_t)(line - acc))) != NULL) {
			*nl = '\0';
			printf("RPMSG_SI_RX %s\n", line);
			long seq;
			if (sscanf(line, "hb seq=%ld", &seq) == 1) {
				if (last_seq >= 0 && seq != last_seq + 1) gaps++;
				last_seq = seq; n_hb++;
			}
			line = nl + 1;
		}
		used -= (size_t)(line - acc);
		memmove(acc, line, used);
		if (used == sizeof(acc) - 1) used = 0;   /* a line longer than the buffer: drop it */
		fflush(stdout);
	}
	if (gaps) { printf("RPMSG_LISTEN_FAIL reason=seq_gap n=%ld\n", n_hb); return 1; }
	if (seconds > 0 && n_hb < seconds - 2) { printf("RPMSG_LISTEN_FAIL reason=too_few n=%ld want=%d\n", n_hb, seconds - 2); return 1; }
	printf("RPMSG_LISTEN_PASS n=%ld gaps=%ld\n", n_hb, gaps);
	return 0;
}

int main(int argc, char **argv)
{
	const char *service = NULL;
	const char *devpath_opt = NULL;
	int count = 100, timeout_s = 5, opt, i, echo_mode = 0, listen_s = -1;
	uint32_t dst = 0;
	uint64_t before, after;
	char devpath[64], tx[128], rx[128], first_rx[128];
	ssize_t first_len = -1;
	int ctrl = -1, ept = -1;
	struct rpmsg_endpoint_info info;

	while ((opt = getopt(argc, argv, "s:n:t:el:d:")) != -1) {
		switch (opt) {
		case 's': service = optarg; break;
		case 'n': count = atoi(optarg); break;
		case 't': timeout_s = atoi(optarg); break;
		case 'e': echo_mode = 1; break;
		case 'l': listen_s = atoi(optarg); break;
		case 'd': devpath_opt = optarg; break;
		default:
			printf("RPMSG_PING_FAIL reason=bad_args\n");
			fprintf(stderr,
				"usage: %s -s <service> [-n count] [-t timeout_s] [-e] [-l seconds] [-d device]\n",
				argv[0]);
			return 1;
		}
	}
	if (!service || count < 1 || timeout_s < 1 || timeout_s > 2147483) {
		printf("RPMSG_PING_FAIL reason=bad_args\n");
		return 1;
	}
	if (devpath_opt) {
		ept = open(devpath_opt, O_RDWR | O_NOCTTY);
		if (ept < 0) {
			printf("RPMSG_PING_FAIL reason=open_eptdev dev=%s errno=%d\n",
			       devpath_opt, errno);
			return 1;
		}
	} else {
		if (find_service(service, &dst)) {
			printf("RPMSG_PING_FAIL reason=service_not_found service=%s\n",
			       service);
			return 1;
		}
		ctrl = open_ctrl();
		if (ctrl < 0) {
			printf("RPMSG_PING_FAIL reason=no_rpmsg_ctrl\n");
			fprintf(stderr, "hint: modprobe rpmsg_ctrl rpmsg_char?\n");
			return 1;
		}
		memset(&info, 0, sizeof(info));
		snprintf(info.name, sizeof(info.name), "%s", service);
		info.src = RPMSG_ADDR_ANY;
		info.dst = dst;
		before = eptdev_snapshot();
		if (ioctl(ctrl, RPMSG_CREATE_EPT_IOCTL, &info)) {
			printf("RPMSG_PING_FAIL reason=create_ept errno=%d\n", errno);
			return 1;
		}
		after = eptdev_snapshot() & ~before;
		if (!after) {
			printf("RPMSG_PING_FAIL reason=no_new_eptdev\n");
			return 1;
		}
		for (i = 0; i < 64; i++)
			if (after & (1ULL << i))
				break;
		snprintf(devpath, sizeof(devpath), "/dev/rpmsg%d", i);
		ept = open(devpath, O_RDWR);
		if (ept < 0) {
			printf("RPMSG_PING_FAIL reason=open_eptdev dev=%s errno=%d\n",
			       devpath, errno);
			return 1;
		}
	}
	if (listen_s >= 0)
		return listen_loop(ept, listen_s);
	for (i = 0; i < count; i++) {
		struct pollfd pfd = { .fd = ept, .events = POLLIN };
		int n = snprintf(tx, sizeof(tx), "x5h-rpmsg-ping seq=%d", i);

		if (write(ept, tx, (size_t)n + 1) != n + 1) {
			printf("RPMSG_PING_FAIL reason=write seq=%d errno=%d\n",
			       i, errno);
			goto fail;
		}
		if (poll(&pfd, 1, timeout_s * 1000) != 1) {
			printf("RPMSG_PING_FAIL reason=rx_timeout seq=%d\n", i);
			goto fail;
		}
		if (pfd.revents & (POLLERR | POLLHUP)) {
			printf("RPMSG_PING_FAIL reason=channel_closed seq=%d revents=0x%x\n",
			       i, (unsigned int)pfd.revents);
			goto fail;
		}
		memset(rx, 0, sizeof(rx));
		ssize_t r = read(ept, rx, sizeof(rx));
		if (r < 0) {
			printf("RPMSG_PING_FAIL reason=read seq=%d errno=%d\n",
			       i, errno);
			goto fail;
		}
		if (r == 0) {
			printf("RPMSG_PING_FAIL reason=empty_reply seq=%d\n", i);
			goto fail;
		}
		if (echo_mode) {
			if (r < n + 1 || memcmp(tx, rx, (size_t)n + 1)) {
				printf("RPMSG_PING_FAIL reason=payload_mismatch seq=%d len=%zd rx='%.*s'\n",
				       i, r, (int)r, rx);
				goto fail;
			}
		} else if (first_len < 0) {
			first_len = r;
			memcpy(first_rx, rx, (size_t)r);
		} else if (r != first_len || memcmp(rx, first_rx, (size_t)r)) {
			/* A responder firmware answers every request with the same
			 * constant. Drift means a corrupted or mis-sequenced vring,
			 * which a mere "something came back" check would not catch. */
			printf("RPMSG_PING_FAIL reason=reply_drift seq=%d len=%zd rx='%.*s'\n",
			       i, r, (int)r, rx);
			goto fail;
		}
	}
	ioctl(ept, RPMSG_DESTROY_EPT_IOCTL);
	close(ept);
	if (ctrl >= 0)
		close(ctrl);
	if (echo_mode)
		printf("RPMSG_PING_PASS n=%d service=%s dst=0x%x mode=echo\n",
		       count, service, dst);
	else
		printf("RPMSG_PING_PASS n=%d service=%s dst=0x%x mode=responder reply='%.*s'\n",
		       count, service, dst,
		       (int)strnlen(first_rx, (size_t)first_len), first_rx);
	return 0;
fail:
	if (ept >= 0) {
		ioctl(ept, RPMSG_DESTROY_EPT_IOCTL);
		close(ept);
	}
	if (ctrl >= 0)
		close(ctrl);
	return 1;
}
