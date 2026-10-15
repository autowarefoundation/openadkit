#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* The S-CORE health monitor for one VisionPilot process. VisionPilot loads
 * this library with dlopen, so the C boundary removes any compiler dependency
 * between the S-CORE GCC 12 build and the VisionPilot build.
 * Every function returns 0 on success and a negative value on error. */
int score_vp_init(uint32_t frame_max_ms);
int score_vp_report_running(void);
int score_vp_frame_begin(void);
int score_vp_frame_end(void);
#ifdef __cplusplus
}
#endif
