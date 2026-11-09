// A long-running integrator node. It links diagnostic_updater on purpose: a
// mismatch between the devel image it is built in and the runtime image it
// runs in (the class of bug that broke Jazzy's ADAPI) makes it fail to start.
#include <chrono>
#include <memory>

#include <diagnostic_updater/diagnostic_updater.hpp>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("acme_probe");
  diagnostic_updater::Updater updater(node);
  updater.setHardwareID("acme");
  auto publisher = node->create_publisher<std_msgs::msg::String>("/acme/probe", 10);
  auto timer = node->create_wall_timer(std::chrono::seconds(1), [&publisher]() {
    std_msgs::msg::String message;
    message.data = "integrator overlay is running";
    publisher->publish(message);
  });
  RCLCPP_INFO(node->get_logger(), "acme_probe started");
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
