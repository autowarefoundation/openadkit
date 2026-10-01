/* VisionPilot stand-in for the SIL harness: 10 Hz frames through
 * libscore_vp.so, 30 ms of work and 70 ms idle. SIGUSR1 adds 200 ms of work to
 * every later frame (D-slow). SIGTERM ends it. Both need handlers: SIGUSR1's
 * default action ends the process, and SIGTERM must end the loop cleanly.
 * Env: SCORE_VP_FRAME_MAX_MS (required). */
#include "score_vp.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static volatile sig_atomic_t g_stop;
static volatile sig_atomic_t g_slow;
static void on_term(int s) { (void)s; g_stop = 1; }
static void on_usr1(int s) { (void)s; g_slow = 1; }

int main(void)
{
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);
    signal(SIGUSR1, on_usr1);
    const char* max = getenv("SCORE_VP_FRAME_MAX_MS");
    if (max == NULL || score_vp_init((uint32_t)atoi(max)) != 0) return 1;
    const struct timespec work = {0, 30L * 1000 * 1000};
    const struct timespec slow_work = {0, 230L * 1000 * 1000};
    const struct timespec idle = {0, 70L * 1000 * 1000};
    for (long frame = 0; !g_stop; ++frame)
    {
        score_vp_frame_begin();
        nanosleep(g_slow ? &slow_work : &work, NULL);
        score_vp_frame_end();
        if (frame == 1)
        {
            printf("standin running rc=%d\n", score_vp_report_running());
            fflush(stdout);
        }
        nanosleep(&idle, NULL);
    }
    return 0;
}
