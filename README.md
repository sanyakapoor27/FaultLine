# Faultline

Faultline is a lightweight chaos engineering framework designed to inject faults into your systems using a declarative DSL (Domain Specific Language). It helps test the resilience of applications by introducing controlled network issues, container failures, and conditional chaos actions based on real-time metrics from Prometheus.

## Features

### Custom DSL

Define chaos scenarios in a simple text format:

```dsl
scenario docker-test {
    node test-backend-1 {
        delay 15 s
    }
}
```

### Conditional Chaos

Trigger chaos only when Prometheus metrics meet certain conditions:

```dsl
scenario docker-auto-chaos {
    if (process_resident_memory_bytes > 2000000) == 0 {
        node test-backend-1 {
            loss 50%
        }
    }
}
```

### Docker Support

Run scenarios that directly target Docker containers.

### Network Chaos Actions

* Delay (latency injection)
* Jitter
* Packet loss
* Bandwidth throttling

### Pluggable Metrics

Works with Prometheus queries for conditional checks.

## Requirements

* Linux VM / Host (Ubuntu 20.04+ recommended)
* Python 3.10+
* Docker Engine & Docker Compose
* Prometheus (running at `http://localhost:9090`)
* pip + virtualenv

## Setup

1. Clone the repository:

```bash
git clone https://github.com/yourusername/faultline.git
cd faultline
```

2. Create and activate a virtual environment:

```bash
python3 -m venv myenv
source myenv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. (Optional) Allow non-root Docker access:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

5. Run Prometheus:

```bash
docker run -d --name prometheus -p 9090:9090 prom/prometheus
```

Or configure your own `prometheus.yml`.

## Usage

1. Write a scenario file (`test.chaos`):

```dsl
scenario docker-test {
    node backend {
        restart
    }
}
```

2. Run Faultline:

```bash
python main.py test.chaos --target docker
```

3. Conditional example:

```dsl
scenario docker-auto-chaos {
    if (container_cpu_usage_seconds_total > 0.8){
        link frontend -> backend {
            bandwidth 5mbps duration 30 s
            
        }
    }
}
```
