#include "score_vp.h"

#include <score/mw/health/health_monitor.h>
#include "score/mw/log/logger.h"
#include <score/mw/log/rust/stdout_logger_init.h>

#include <fcntl.h>
#include <unistd.h>

#include <chrono>
#include <cstdlib>
#include <optional>

namespace
{
using namespace score::mw::health;

score::mw::log::Logger& Log()
{
    static score::mw::log::Logger& logger = score::mw::log::CreateLogger("VP", "VisionPilot health");
    return logger;
}

std::optional<HealthMonitor> g_hm;
std::optional<deadline::DeadlineMonitor> g_monitor;
std::optional<deadline::Deadline> g_deadline;
std::optional<deadline::DeadlineHandle> g_running;
bool g_hm_started = false;
bool g_failure_logged = false;
}  // namespace

extern "C" int score_vp_init(uint32_t frame_max_ms)
{
    // The Rust health monitor logs (context HMON) go to stdout: the Rust DLT
    // bridge does not build for aarch64 Linux at logging 0.2.4.
    score::mw::log::rust::StdoutLoggerBuilder().Context("HMON").LogLevel(score::mw::log::rust::LogLevel::Info).SetAsDefaultLogger();
    // The supervisor client aborts without these two. The LM sets
    // LCM_ALIVE_INTERFACE_PATH only for Reporting_And_Supervised components.
    if (std::getenv("IDENTIFIER") == nullptr || std::getenv("LCM_ALIVE_INTERFACE_PATH") == nullptr)
    {
        Log().LogWarn() << "no LM supervision environment, health monitor disabled";
        return 0;
    }
    auto builder = deadline::DeadlineMonitorBuilder().add_deadline(
        DeadlineTag("frame"), TimeRange(std::chrono::milliseconds(0), std::chrono::milliseconds(frame_max_ms)));
    auto hm = HealthMonitorBuilder()
                  .add_deadline_monitor(MonitorTag("vp"), std::move(builder))
                  .with_internal_processing_cycle(std::chrono::milliseconds(50))
                  .with_supervisor_api_cycle(std::chrono::milliseconds(50))
                  .build();
    if (!hm.has_value())
    {
        return -1;
    }
    g_hm.emplace(std::move(*hm));
    auto monitor = g_hm->get_deadline_monitor(MonitorTag("vp"));
    if (!monitor.has_value())
    {
        return -2;
    }
    g_monitor.emplace(std::move(*monitor));
    auto deadline = g_monitor->get_deadline(DeadlineTag("frame"));
    if (!deadline.has_value())
    {
        return -3;
    }
    g_deadline.emplace(std::move(*deadline));
    Log().LogInfo() << "health monitor ready, frame budget ms:" << frame_max_ms;
    return 0;
}

extern "C" int score_vp_report_running(void)
{
    // The LM cannot take a kRunning report from inside a container:
    // report_running() checks that the caller is the PID the LM forked, and
    // the container process never is. The LM waits for this file instead
    // (ready_condition.file_state).
    //
    // Alive notifications start here, before the file appears, and not in
    // score_vp_init. The LM reads the alive channel only once this process is
    // Running, then takes the whole backlog in one cycle into a 100-event
    // buffer (kDefaultAliveSupCheckpointBufferElements). At one notification
    // per 50 ms, a startup longer than about 5 s overflows it and the
    // supervision expires (board 2, 2026-10-01: a 7.6 s Startup).
    if (g_hm && !g_hm_started)
    {
        g_hm->start();
        g_hm_started = true;
        Log().LogInfo() << "health monitor started";
    }
    const char* path = std::getenv("SCORE_VP_READY_FILE");
    if (path == nullptr)
    {
        return 0;
    }
    const int fd = ::open(path, O_CREAT | O_WRONLY | O_CLOEXEC, 0644);
    if (fd < 0)
    {
        return -1;
    }
    ::close(fd);
    Log().LogInfo() << "reported running";
    return 0;
}

extern "C" int score_vp_frame_begin(void)
{
    if (!g_deadline)
    {
        return 0;
    }
    auto handle = g_deadline->start();
    if (!handle.has_value())
    {
        // A failed deadline stays failed, and the health monitor has stopped
        // its alive notifications. This is the one DLT line that says why.
        if (!g_failure_logged)
        {
            Log().LogError() << "frame deadline failed, alive notifications stopped";
            g_failure_logged = true;
        }
        return -1;
    }
    g_running.emplace(std::move(*handle));
    return 0;
}

extern "C" int score_vp_frame_end(void)
{
    if (!g_running)
    {
        return 0;
    }
    g_running->stop();
    g_running.reset();
    return 0;
}
