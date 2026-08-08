```mermaid
flowchart LR
    CORE["autoware:core-devel (build)<br/>autoware:base (runtime)"] --> UC["universe-common"]
    CUDA["autoware:base-cuda-{devel,runtime}"] --> SPC["sensing-perception-cuda"]
    UC --> SP["sensing-perception"]
    UC --> LM["localization-mapping"]
    UC --> PC["planning-control"]
    UC --> VS["vehicle-system"]
    UC --> API["api"]
    UC --> VIZ["visualizer"]
    UC --> SIM["simulator"]
    UC --> SPC
    SIM --> CARLA["carla-interface"]
```
