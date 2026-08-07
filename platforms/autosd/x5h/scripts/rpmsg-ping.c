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
 * Exit 0 + "RPMSG_PING_PASS n=<count>" on success; exit 1 + a
 * "RPMSG_PING_FAIL reason=..." line on any failure.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

int main(int argc, char **argv)
{
	const char *service = NULL;
	int count = 100, timeout_s = 5, opt, i, echo_mode = 0;
	uint32_t dst = 0;
	uint64_t before, after;
	char devpath[64], tx[128], rx[128], first_rx[128];
	ssize_t first_len = -1;
	int ctrl, ept = -1;
	struct rpmsg_endpoint_info info;

	while ((opt = getopt(argc, argv, "s:n:t:e")) != -1) {
		switch (opt) {
		case 's': service = optarg; break;
		case 'n': count = atoi(optarg); break;
		case 't': timeout_s = atoi(optarg); break;
		case 'e': echo_mode = 1; break;
		default:
			printf("RPMSG_PING_FAIL reason=bad_args\n");
			fprintf(stderr,
				"usage: %s -s <service> [-n count] [-t timeout_s] [-e]\n",
				argv[0]);
			return 1;
		}
	}
	if (!service || count < 1 || timeout_s < 1 || timeout_s > 2147483) {
		printf("RPMSG_PING_FAIL reason=bad_args\n");
		return 1;
	}
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
	close(ctrl);
	return 1;
}
