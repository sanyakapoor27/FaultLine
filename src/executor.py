import subprocess
import tempfile
import yaml
import time
import threading
import sys
import re
import docker
import requests
import json
import os
from typing import Optional
from src.ast import *
from src.prom_client import PromClient

class Executor:
    
    def __init__(self, dry_run=False, target='kubernetes', prom_endpoint: str = "http://localhost:9090"):
        self.dry_run = dry_run
        self.target = target.lower()
        self.generated_manifests = []
        self.applied_docker_chaos = {}
        
        self.applied_k8s_chaos_rules = {} #The format: {pod_name: ['tc_rule_id']}
        
        # Initialize PromClient
        try:
            self.prom_client = PromClient(endpoint=prom_endpoint)
        except ValueError as e:
            print(f"[Network Chaos] ERROR: {e}")
            sys.exit(1)


        # Initialize Docker client if target is 'docker'
        if self.target == 'docker':
            try:
                self.docker_client = docker.from_env()
                print("[Network Chaos] Connected to Docker daemon.")
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to connect to Docker daemon. Is it running? {e}")
                sys.exit(1)


    def execute(self, ast: Program):
        """Execute the AST by traversing its statements."""
        print(f"[Network Chaos] Starting execution for target: {self.target}...")
        for statement in ast.statements:
            self._execute_statement(statement)
        print(f"[Network Chaos] Execution complete. Generated {len(self.generated_manifests)} manifests.")


    def _execute_statement(self, stmt: Statement):
        """Executes a single statement based on its type."""
        
        if isinstance(stmt, Scenario):
            print(f"[Network Chaos] Executing scenario: {stmt.name}")
            for chaos_stmt in stmt.statements:
                self._execute_statement(chaos_stmt)
        
        elif isinstance(stmt, IfStatement):
            self._execute_if_stmt(stmt)
            
        elif isinstance(stmt, LoopStatement):
            self._execute_loop_stmt(stmt)
        
        elif isinstance(stmt, ChaosStatement):
            self._execute_chaos(stmt)
        
        else:
            print(f"[Network Chaos] Skipping wrong statement type: {type(stmt).__name__}")
    
    def _execute_if_stmt(self, if_stmt: IfStatement):
        """Evaluates a condition and executes the appropriate branch."""
        print(f"[Network Chaos] Evaluating 'if' condition: {if_stmt.condition.metric} {if_stmt.condition.operator} {if_stmt.condition.value}")
        
        if self._evaluate_condition(if_stmt.condition):
            print("[Network Chaos] Condition is TRUE. Executing 'then' block...")
            for stmt in if_stmt.then_branch:
                self._execute_statement(stmt)
        elif if_stmt.else_branch:
            print("[Network Chaos] Condition is FALSE. Executing 'else' block...")
            for stmt in if_stmt.else_branch:
                self._execute_statement(stmt)
        else:
            print("[Network Chaos] Condition is FALSE. No 'else' block to execute.")


    def _execute_loop_stmt(self, loop_stmt: LoopStatement):
        """Executes the loop body a specified number of times."""
        print(f"[Network Chaos] Executing 'for' loop from {loop_stmt.start} to {loop_stmt.end}")
        
        for i in range(loop_stmt.start, loop_stmt.end + 1):
            print(f"[Network Chaos] Loop iteration: {i}")
            for stmt in loop_stmt.body:
                self._execute_statement(stmt)


    def _evaluate_condition(self, condition: Condition) -> bool:
        """
        Evaluates a metric condition by querying Prometheus.
        """
        print(f"[Network Chaos] Evaluating condition: {condition.metric} {condition.operator} {condition.value}")
        
        promql_query = condition.metric
        
        result_value = self.prom_client.query(promql_query)
        
        if result_value is None:
            print(f"[Network Chaos] WARNING: No result found for metric '{condition.metric}'. Condition evaluates to False.")
            return False
            
        if condition.operator == '>':
            return result_value > condition.value
        elif condition.operator == '<':
            return result_value < condition.value
        elif condition.operator == '>=':
            return result_value >= condition.value
        elif condition.operator == '<=':
            return result_value <= condition.value
        elif condition.operator == '==':
            return result_value == condition.value
        elif condition.operator == '!=':
            return result_value != condition.value
        
        print(f"[Network Chaos] ERROR: Unknown operator '{condition.operator}'. Condition evaluates to False.")
        return False
    
    def _execute_chaos(self, stmt: ChaosStatement):
        """Dispatches chaos statements based on the target environment."""
        if self.target == 'kubernetes':
            if isinstance(stmt, PartitionStatement):
                self._execute_partition_k8s(stmt)
            elif isinstance(stmt, NodeStatement):
                self._execute_node_k8s(stmt)
            elif isinstance(stmt, LinkStatement):
                self._execute_link_k8s(stmt)
        elif self.target == 'docker':
            if isinstance(stmt, NodeStatement):
                self._execute_node_docker(stmt)
            elif isinstance(stmt, PartitionStatement):
                print(f"[Network Chaos] Skipping wrong Docker Partition chaos: {type(stmt).__name__}")
            elif isinstance(stmt, LinkStatement):
                self._execute_link_docker(stmt)
        else:
            print(f"[Network Chaos] ERROR: Unknown target environment: {self.target}")
    
    def _get_container_pid(self, container_id: str):
        """Gets the PID of a running container from its ID."""
        try:
            container_info = self.docker_client.api.inspect_container(container_id)
            pid = container_info['State']['Pid']
            if pid == 0:
                print(f"[Network Chaos] ERROR: Container '{container_id}' is not running (PID is 0).")
                return None
            return str(pid)
        except docker.errors.NotFound:
            print(f"[Network Chaos] ERROR: Container '{container_id}' not found when getting PID.")
            return None
        except Exception as e:
            print(f"[Network Chaos] ERROR: Failed to get PID for container '{container_id}': {e}")
            return None
    
    def _execute_node_docker(self, node_stmt: NodeStatement):
        """
        Finds the specified Docker container and applies all chaos actions to it.
        """
        print(f"[Network Chaos] Applying Node chaos on Docker container '{node_stmt.service}'...")
        try:
            container = self.docker_client.containers.get(node_stmt.service)
        except docker.errors.NotFound:
            print(f"[Network Chaos] ERROR: Docker container '{node_stmt.service}' not found.")
            return
        except Exception as e:
            print(f"[Network Chaos] ERROR: Failed to get Docker container '{node_stmt.service}': {e}")
            return

        host_veth = None

        for action in node_stmt.actions:
            if isinstance(action, (DelayAction, LossAction, BandwidthAction)):
                if host_veth is None:
                    pid = self._get_container_pid(container.id)
                    if not pid:
                        print(f"[Network Chaos] ERROR: Could not get PID for container '{container.name}', skipping network actions.")
                        continue
                    
                    host_veth = self._get_container_veth(pid)
                    if not host_veth:
                        print(f"[Network Chaos] ERROR: Could not find host veth for container '{container.name}', skipping network actions.")
                        continue

                # specific network actions
                if isinstance(action, DelayAction):
                    self._apply_docker_delay(container, action, host_veth)
                elif isinstance(action, LossAction):
                    self._apply_docker_loss(container, action, host_veth)
                elif isinstance(action, BandwidthAction):
                    self._apply_docker_bandwidth(container, action, host_veth)

            # non network actions r here
            elif isinstance(action, CrashAction):
                self._apply_docker_crash(container, action)
                
            elif isinstance(action, RestartAction):
                self._apply_docker_restart(container, action)
                
            else:
                print(f"[Network Chaos] ERROR: wrong Docker action type: {type(action).__name__}")
    
    def _execute_partition_k8s(self, partition: PartitionStatement):
        """Execute a network partition in Kubernetes with timed cleanup."""
        print(f"[Network Chaos] Creating network partition on Kubernetes...")
        
        from_labels = self._filter_to_labels(partition.from_filter)
        to_labels = self._filter_to_labels(partition.to_filter)
        
        yaml_content = self._generate_network_policy(from_labels, to_labels)
        policy_name = yaml.safe_load(yaml_content)['metadata']['name']
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            manifest_path = f.name
        
        self.generated_manifests.append(manifest_path)
        
        if self.dry_run:
            print(f"[Network Chaos] [DRY RUN] Would apply NetworkPolicy named '{policy_name}':")
            print(yaml_content)
        else:
            try:
                subprocess.run(['kubectl', 'apply', '-f', manifest_path], check=True, capture_output=True)
                print(f"[Network Chaos] NetworkPolicy '{policy_name}' applied successfully.")
                
                if partition.duration:
                    duration_seconds = partition.duration.to_seconds()
                    print(f"[Network Chaos] Partition will last for {duration_seconds} seconds.")
                    
                    timer = threading.Timer(duration_seconds, self._delete_network_policy, args=[policy_name])
                    timer.start()
                    print(f"[Network Chaos] Scheduled cleanup for '{policy_name}' in {duration_seconds} seconds.")


            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply NetworkPolicy: {e.stderr}")
            except FileNotFoundError:
                print("[Network Chaos] ERROR: kubectl not found. Please ensure it is installed.")


    def _delete_network_policy(self, name: str):
        """Deletes a NetworkPolicy by name."""
        print(f"[Network Chaos] Deleting NetworkPolicy '{name}'...")
        try:
            subprocess.run(['kubectl', 'delete', 'networkpolicy', name], check=True, capture_output=True)
            print(f"[Network Chaos] NetworkPolicy '{name}' deleted successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[Network Chaos] ERROR: Failed to delete NetworkPolicy: {e.stderr}")
        except FileNotFoundError:
            print("[Network Chaos] ERROR: kubectl not found. Cannot perform cleanup.")
    
    def _filter_to_labels(self, filter_obj: Filter) -> dict:
        """Convert a Filter object to a dictionary of labels"""
        labels = {}
        for pair in filter_obj.pairs:
            labels[pair.key] = pair.value
        return labels


    def _generate_network_policy(self, from_labels: dict, to_labels: dict) -> str:
        """Generate a Kubernetes NetworkPolicy YAML that denies traffic in both directions."""
        policy_name = f"chaos-partition-{abs(hash(str(from_labels) + str(to_labels)))}"
        policy = {
            'apiVersion': 'networking.k8s.io/v1',
            'kind': 'NetworkPolicy',
            'metadata': {
                'name': policy_name,
                'namespace': 'default'
            },
            'spec': {
                'podSelector': {
                    'matchLabels': from_labels
                },
                'policyTypes': ['Egress'],
                'egress': [
                    {
                        'to': [
                            {
                                'podSelector': {
                                    'matchLabels': to_labels
                                }
                            }
                        ],
                        'ports': []
                    }
                ]
            }
        }
        return yaml.dump(policy, sort_keys=False)

    def _get_container_veth(self, container_pid: str) -> Optional[str]:
        """
        Finds the host-side veth interface name for a given container PID.
        This version uses the /sys filesystem for maximum reliability and avoids
        parsing the output of the 'ip' command.
        """
        try:
            #Findingg the 'iflink' of the interface inside the container's network namespace.
            #This number is the 'ifindex' of its peer on the host.
            peer_ifindex = None
            
            #here we get a list of network interfaces which r inside the container
            cmd_list_ifaces = ['nsenter', '-t', container_pid, '-n', 'ls', '/sys/class/net']
            interfaces_raw = subprocess.run(
                cmd_list_ifaces, check=True, capture_output=True, text=True
            ).stdout
            container_ifaces = interfaces_raw.strip().split()

            for iface in container_ifaces:
                #we dont want the first interface that is loopback 'lo' device
                if iface == 'lo':
                    continue
                
                cmd_read_iflink = ['nsenter', '-t', container_pid, '-n', 'cat', f'/sys/class/net/{iface}/iflink']
                
                iflink_result = subprocess.run(
                    cmd_read_iflink, check=True, capture_output=True, text=True
                )
                
                peer_ifindex = iflink_result.stdout.strip()
                break #we can stop as we got valid interface now

            if not peer_ifindex:
                print(f"[Network Chaos] ERROR: Could not find 'iflink' for any interface in container PID {container_pid}.")
                return None

            #searching host interfaces for one with an 'ifindex' that matches the 'iflink' we found
            host_ifaces_path = '/sys/class/net'
            for host_iface_name in os.listdir(host_ifaces_path):
                
                try:
                    ifindex_path = os.path.join(host_ifaces_path, host_iface_name, 'ifindex')
                    with open(ifindex_path, 'r') as f:
                        ifindex = f.read().strip()
                        
                        if ifindex == peer_ifindex:
                            print(f"[Network Chaos] Found host veth '{host_iface_name}' for container PID {container_pid}.")
                            return host_iface_name
                except (IOError, OSError):
                    continue

            print(f"[Network Chaos] WARNING: No host veth found for PID {container_pid} matching peer ifindex {peer_ifindex}")
            return None

        except subprocess.CalledProcessError as e:
            print(f"[Network Chaos] ERROR: A command failed while finding veth for PID {container_pid}.")
            print(f"  Command: {' '.join(e.cmd)}")
            print(f"  Stderr: {e.stderr}")
            return None
        except Exception as e:
            print(f"[Network Chaos] ERROR: An unexpected error occurred while finding veth for PID {container_pid}: {e}")
            return None

                
    def _apply_docker_delay(self, container, action: DelayAction, host_veth: str):
        """Applies network delay to a Docker container using `tc` on the host side."""
        duration_ms = int(action.duration.value) if action.duration.unit == 'ms' else int(action.duration.to_seconds() * 1000)
        
        command = f"tc qdisc add dev {host_veth} root netem delay {duration_ms}ms"
        if action.jitter:
            jitter_ms = int(action.jitter.value) if action.jitter.unit == 'ms' else int(action.jitter.to_seconds() * 1000)
            command += f" {jitter_ms}ms"
            
        print(f"[Network Chaos] Applying command on host: {command}")
        
        if not self.dry_run:
            try:
                subprocess.run(command.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {duration_ms}ms delay to '{container.name}'.")
                self._schedule_docker_cleanup(container.id, 'tc', action.duration.to_seconds())
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply delay to '{container.name}': {e}")
                
    def _apply_docker_loss(self, container, action: LossAction, host_veth: str):
        """Applies packet loss to a Docker container using `tc` on the host side."""
        command = f"tc qdisc add dev {host_veth} root netem loss {action.percentage}%"
        print(f"[Network Chaos] Applying command on host: {command}")
        
        if not self.dry_run:
            try:
                subprocess.run(command.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {action.percentage}% packet loss to '{container.name}'.")
                self._schedule_docker_cleanup(container.id, 'tc', 30) # Default duration for indefinite actions
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply loss to '{container.name}': {e}")
                
    def _apply_docker_crash(self, container, action: CrashAction):
        """Crashes a Docker container by stopping it."""
        print(f"[Network Chaos] Stopping container '{container.name}'...")
        if not self.dry_run:
            try:
                container.stop()
                print(f"[Network Chaos] Container '{container.name}' stopped successfully.")
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to stop container '{container.name}': {e}")
    
    def _apply_docker_restart(self, container, action: RestartAction):
        """Restarts a Docker container."""
        print(f"[Network Chaos] Restarting container '{container.name}'...")
        if not self.dry_run:
            try:
                container.restart()
                print(f"[Network Chaos] Container '{container.name}' restarted successfully.")
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to restart container '{container.name}': {e}")
    
    def _apply_docker_bandwidth(self, container, action: BandwidthAction, host_veth: str):
        """Applies bandwidth limits to a Docker container using `tc` on the host side."""
        rate_kbps = action.rate.value
        if action.rate.unit == 'mbps':
            rate_kbps *= 1000
        elif action.rate.unit == 'gbps':
            rate_kbps *= 1000000


        command = f"tc qdisc add dev {host_veth} root tbf rate {rate_kbps}kbps burst 10kb latency 70ms"
        print(f"[Network Chaos] Applying command on host: {command}")
        
        if not self.dry_run:
            try:
                subprocess.run(command.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Applied {action.rate.value}{action.rate.unit} bandwidth limit to '{container.name}'.")
                self._schedule_docker_cleanup(container.id, 'tc', 30) # Default duration for indefinite actions
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply bandwidth limit to '{container.name}': {e}")
                
    def _schedule_docker_cleanup(self, container_id: str, rule_type: str, duration_seconds: float):
        """Schedules the cleanup of a network rule on a Docker container after a duration."""
        timer = threading.Timer(duration_seconds, self._cleanup_docker_network_rule, args=[container_id, rule_type])
        timer.start()
        print(f"[Network Chaos] Scheduled cleanup for container '{container_id}' ({rule_type}) in {duration_seconds} seconds.")


    def _cleanup_docker_network_rule(self, container_id: str, rule_type: str):
        """Cleans up a specific network rule on a Docker container."""
        print(f"[Network Chaos] Cleaning up {rule_type} rule on container '{container_id}'...")
        if not self.dry_run:
            try:
                container = self.docker_client.containers.get(container_id)
                container_pid = container.attrs['State']['Pid']
                host_veth = self._get_container_veth(str(container_pid))
                if host_veth:
                    subprocess.run(f"tc qdisc del dev {host_veth} root".split(), check=True, capture_output=True, text=True)
                    print(f"[Network Chaos] Cleaned up {rule_type} rule on '{container_id}'.")
                else:
                    print(f"[Network Chaos] WARNING: Could not find host veth for container '{container_id}'. Skipping cleanup.")
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to clean up {rule_type} rule on '{container_id}': {e}")

    
    def _execute_node_k8s(self, node_stmt: NodeStatement):
        """
        Executes node-level chaos in a Kubernetes cluster.
        This method will find the pod and dispatch to the correct action.
        """
        service_name = node_stmt.service
        
        try:
            pod_name_result = subprocess.run(
                ['kubectl', 'get', 'pods', '-l', f'service={service_name}', '-o', 'jsonpath={{.items[0].metadata.name}}'],
                check=True,
                capture_output=True,
                text=True
            )
            pod_name = pod_name_result.stdout.strip()
            if not pod_name:
                print(f"[Network Chaos] ERROR: No pods found for service '{service_name}'. Skipping chaos.")
                return
            print(f"[Network Chaos] Found pod '{pod_name}' for service '{service_name}'.")


        except subprocess.CalledProcessError as e:
            print(f"[Network Chaos] ERROR: Could not find pod for service '{service_name}': {e.stderr}")
            return
            
        for action in node_stmt.actions:
            if isinstance(action, DelayAction):
                self._apply_k8s_delay(pod_name, action)
            elif isinstance(action, LossAction):
                self._apply_k8s_loss(pod_name, action)
            elif isinstance(action, CrashAction):
                self._apply_k8s_crash(pod_name)
            elif isinstance(action, RestartAction):
                self._apply_k8s_restart(service_name)
            else:
                print(f"[Network Chaos] ERROR: wrong Kubernetes action type: {type(action).__name__}")


    def _execute_link_k8s(self, link_stmt: LinkStatement):
        """
        Executes link-level chaos in Kubernetes by applying tc rules on pods.
        """
        from_service = link_stmt.from_service
        to_service = link_stmt.to_service
        
        to_service_ips = self._get_k8s_pod_ips_by_service(to_service)
        if not to_service_ips:
            print(f"[Network Chaos] ERROR: No pods found for 'to' service '{to_service}'. Skipping link chaos.")
            return


        from_pod_names = self._get_k8s_pod_names_by_service(from_service)
        if not from_pod_names:
            print(f"[Network Chaos] ERROR: No pods found for 'from' service '{from_service}'. Skipping link chaos.")
            return
            
        for pod_name in from_pod_names:
            print(f"[Network Chaos] Applying link chaos from pod '{pod_name}' to service '{to_service}'...")
            for action in link_stmt.actions:
                if isinstance(action, DelayAction):
                    self._apply_k8s_link_delay(pod_name, action, to_service_ips)
                elif isinstance(action, LossAction):
                    self._apply_k8s_link_loss(pod_name, action, to_service_ips)
                elif isinstance(action, BandwidthAction):
                    self._apply_k8s_link_bandwidth(pod_name, action, to_service_ips)
                else:
                    print(f"[Network Chaos] ERROR: wrong link action type: {type(action).__name__}")
    
    def _apply_k8s_delay(self, pod_name: str, action: DelayAction):
        """Applies network delay to a Kubernetes pod using `tc`."""
        duration_ms = int(action.duration.value) if action.duration.unit == 'ms' else int(action.duration.to_seconds() * 1000)
        
        command = f"tc qdisc add dev eth0 root netem delay {duration_ms}ms"
        if action.jitter:
            jitter_ms = int(action.jitter.value) if action.jitter.unit == 'ms' else int(action.jitter.to_seconds() * 1000)
            command += f" {jitter_ms}ms"


        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', pod_name, '--', 'sh', '-c', command], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {duration_ms}ms delay to '{pod_name}'.")
                self._schedule_cleanup(pod_name, 'tc_qdisc', action.duration.to_seconds())
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply delay to '{pod_name}': {e.stderr}")


    def _apply_k8s_loss(self, pod_name: str, action: LossAction):
        """Applies packet loss to a Kubernetes pod using `tc`."""
        command = f"tc qdisc add dev eth0 root netem loss {action.percentage}%"


        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', pod_name, '--', 'sh', '-c', command], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {action.percentage}% packet loss to '{pod_name}'.")
                self._schedule_cleanup(pod_name, 'tc_qdisc', 30) # Default duration for indefinite actions
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply loss to '{pod_name}': {e.stderr}")


    def _apply_k8s_crash(self, pod_name: str):
        """Crashes a Kubernetes pod by deleting it."""
        print(f"[Network Chaos] Deleting pod '{pod_name}' to simulate a crash...")
        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'delete', 'pod', pod_name], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Pod '{pod_name}' deleted successfully.")
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to delete pod '{pod_name}': {e.stderr}")


    def _apply_k8s_restart(self, service_name: str):
        """Restarts a Kubernetes deployment associated with a service."""
        print(f"[Network Chaos] Restarting deployment for service '{service_name}'...")
        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'rollout', 'restart', 'deployment', service_name], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Deployment for service '{service_name}' restarted successfully.")
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to restart deployment for service '{service_name}': {e.stderr}")


    def _apply_k8s_link_delay(self, from_pod: str, action: DelayAction, to_ips: list):
        """Applies a link delay from one pod to a list of destination IPs."""
        duration_ms = int(action.duration.value) if action.duration.unit == 'ms' else int(action.duration.to_seconds() * 1000)
        
        commands = [f"tc qdisc add dev eth0 root netem delay {duration_ms}ms" for _ in to_ips]
        command_string = " ; ".join(commands)


        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', from_pod, '--', 'sh', '-c', command_string], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {duration_ms}ms delay from pod '{from_pod}' to destination IPs.")
                self._schedule_cleanup(from_pod, 'tc_qdisc', action.duration.to_seconds())
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply link delay from '{from_pod}': {e.stderr}")


    def _apply_k8s_link_loss(self, from_pod: str, action: LossAction, to_ips: list):
        """Applies packet loss from one pod to a list of destination IPs."""
        commands = [f"tc qdisc add dev eth0 root netem loss {action.percentage}%" for _ in to_ips]
        command_string = " ; ".join(commands)


        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', from_pod, '--', 'sh', '-c', command_string], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {action.percentage}% packet loss from pod '{from_pod}' to destination IPs.")
                self._schedule_cleanup(from_pod, 'tc_qdisc', 30) # Default duration
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply link loss from '{from_pod}': {e.stderr}")


    def _apply_k8s_link_bandwidth(self, from_pod: str, action: BandwidthAction, to_ips: list):
        """Applies bandwidth limits from one pod to a list of destination IPs."""
        rate_kbps = action.rate.value
        if action.rate.unit == 'mbps':
            rate_kbps *= 1000
        elif action.rate.unit == 'gbps':
            rate_kbps *= 1000000


        commands = [f"tc qdisc add dev eth0 root tbf rate {rate_kbps}kbps burst 10kb latency 70ms" for _ in to_ips]
        command_string = " ; ".join(commands)


        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', from_pod, '--', 'sh', '-c', command_string], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Applied {action.rate.value}{action.rate.unit} bandwidth limit from pod '{from_pod}'.")
                self._schedule_cleanup(from_pod, 'tc_qdisc', 30) # Default duration
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to apply link bandwidth limit from '{from_pod}': {e.stderr}")


    def _schedule_cleanup(self, pod_name: str, rule_type: str, duration_seconds: float):
        """Schedules the cleanup of a network rule on a pod after a duration."""
        timer = threading.Timer(duration_seconds, self._cleanup_k8s_network_rule, args=[pod_name, rule_type])
        timer.start()
        print(f"[Network Chaos] Scheduled cleanup for '{pod_name}' ({rule_type}) in {duration_seconds} seconds.")


    def _cleanup_k8s_network_rule(self, pod_name: str, rule_type: str):
        """Cleans up a specific network rule on a pod."""
        print(f"[Network Chaos] Cleaning up {rule_type} rule on pod '{pod_name}'...")
        if not self.dry_run:
            try:
                subprocess.run(['kubectl', 'exec', pod_name, '--', 'sh', '-c', 'tc qdisc del dev eth0 root'], check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Cleaned up {rule_type} rule on '{pod_name}'.")
            except subprocess.CalledProcessError as e:
                print(f"[Network Chaos] ERROR: Failed to clean up {rule_type} rule on '{pod_name}': {e.stderr}")


    def _get_k8s_pod_ips_by_service(self, service_name: str) -> list:
        """Helper to get a list of pod IPs for a given service label."""
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-l', f'service={service_name}', '-o', 'json'],
                check=True, capture_output=True, text=True
            )
            data = json.loads(result.stdout)
            ips = [item['status']['podIP'] for item in data['items'] if 'podIP' in item['status']]
            return ips
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            print(f"[Network Chaos] ERROR: Could not get pod IPs for service '{service_name}': {e}")
            return []


    def _get_k8s_pod_names_by_service(self, service_name: str) -> list:
        """Helper to get a list of pod names for a given service label."""
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-l', f'service={service_name}', '-o', 'json'],
                check=True, capture_output=True, text=True
            )
            data = json.loads(result.stdout)
            names = [item['metadata']['name'] for item in data['items']]
            return names
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            print(f"[Network Chaos] ERROR: Could not get pod names for service '{service_name}': {e}")
            return []
            
    def _execute_link_docker(self, link_stmt: LinkStatement):
        from_service = link_stmt.from_service
        to_service = link_stmt.to_service
        try:
            from_container = self.docker_client.containers.get(from_service)
        except docker.errors.NotFound:
            print(f"[Network Chaos] ERROR: Docker container '{from_service}' not found. Skipping link chaos.")
            return
        try:
            to_container = self.docker_client.containers.get(to_service)
        except docker.errors.NotFound:
            print(f"[Network Chaos] ERROR: Docker container '{to_service}' not found. Skipping link chaos.")
            return

        from_container_pid = from_container.attrs['State']['Pid']
        from_host_veth = self._get_container_veth(str(from_container_pid))
        if not from_host_veth:
            print(f"[Network Chaos] WARNING: Could not find host veth for container '{from_container.name}'. Skipping network chaos.")
            return

        network_name = list(to_container.attrs['NetworkSettings']['Networks'].keys())[0]
        to_ip = to_container.attrs['NetworkSettings']['Networks'][network_name]['IPAddress']
        
        print(f"[Network Chaos] Applying link chaos from '{from_service}' (via host veth '{from_host_veth}') to '{to_service}' at IP '{to_ip}'...")
        
        for action in link_stmt.actions:
            if isinstance(action, DelayAction):
                self._apply_docker_link_delay(from_container, action, from_host_veth, to_ip)
            elif isinstance(action, LossAction):
                self._apply_docker_link_loss(from_container, action, from_host_veth, to_ip)
            elif isinstance(action, BandwidthAction):
                self._apply_docker_link_bandwidth(from_container, action, from_host_veth, to_ip)
            else:
                print(f"[Network Chaos] ERROR: wrong link action type: {type(action).__name__}")
                
    def _apply_docker_link_delay(self, from_container, action: DelayAction, from_host_veth: str, to_ip: str):
        duration_ms = int(action.duration.value) if action.duration.unit == 'ms' else int(action.duration.to_seconds() * 1000)
        command_qdisc = f"tc qdisc add dev {from_host_veth} root handle 1: netem delay {duration_ms}ms"
        if action.jitter:
            jitter_ms = int(action.jitter.value) if action.jitter.unit == 'ms' else int(action.jitter.to_seconds() * 1000)
            command_qdisc += f" {jitter_ms}ms"
        command_filter = f"tc filter add dev {from_host_veth} protocol ip parent 1: prio 1 u32 match ip dst {to_ip} flowid 1:1"
        print(f"[Network Chaos] Applying commands on host: {command_qdisc} ; {command_filter}")
        if not self.dry_run:
            try:
                subprocess.run(command_qdisc.split(), check=True, capture_output=True, text=True)
                subprocess.run(command_filter.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {duration_ms}ms link delay from '{from_container.name}' to '{to_ip}'.")
                self._schedule_docker_cleanup(from_container.id, 'delay', action.duration.to_seconds())
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply link delay from '{from_container.name}': {e}")
                
    def _apply_docker_link_loss(self, from_container, action: LossAction, from_host_veth: str, to_ip: str):
        command_qdisc = f"tc qdisc add dev {from_host_veth} root handle 1: netem loss {action.percentage}%"
        command_filter = f"tc filter add dev {from_host_veth} protocol ip parent 1: prio 1 u32 match ip dst {to_ip} flowid 1:1"
        print(f"[Network Chaos] Applying commands on host: {command_qdisc} ; {command_filter}")
        if not self.dry_run:
            try:
                subprocess.run(command_qdisc.split(), check=True, capture_output=True, text=True)
                subprocess.run(command_filter.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Added {action.percentage}% packet loss from '{from_container.name}' to '{to_ip}'.")
                self._schedule_docker_cleanup(from_container.id, 'loss', 30) # Default duration
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply link loss from '{from_container.name}': {e}")
                
    def _apply_docker_link_bandwidth(self, from_container, action: BandwidthAction, from_host_veth: str, to_ip: str):
        rate_kbps = action.rate.value
        if action.rate.unit == 'mbps':
            rate_kbps *= 1000
        elif action.rate.unit == 'gbps':
            rate_kbps *= 1000000
        command_qdisc = f"tc qdisc add dev {from_host_veth} root handle 1: tbf rate {rate_kbps}kbps burst 10kb latency 70ms"
        command_filter = f"tc filter add dev {from_host_veth} protocol ip parent 1: prio 1 u32 match ip dst {to_ip} flowid 1:1"
        print(f"[Network Chaos] Applying commands on host: {command_qdisc} ; {command_filter}")
        if not self.dry_run:
            try:
                subprocess.run(command_qdisc.split(), check=True, capture_output=True, text=True)
                subprocess.run(command_filter.split(), check=True, capture_output=True, text=True)
                print(f"[Network Chaos] Applied {action.rate.value}{action.rate.unit} bandwidth limit from '{from_container.name}' to '{to_ip}'.")
                self._schedule_docker_cleanup(from_container.id, 'bandwidth', 30) # Default duration
            except Exception as e:
                print(f"[Network Chaos] ERROR: Failed to apply link bandwidth limit from '{from_container.name}': {e}")
                
    def cleanup(self):
        """
        Cleans up all network chaos rules that were applied.
        """
        if self.target == 'kubernetes':
            # Cleanup all NetworkPolicies
            for manifest_path in self.generated_manifests:
                try:
                    name = yaml.safe_load(open(manifest_path))['metadata']['name']
                    self._delete_network_policy(name)
                    os.remove(manifest_path)
                except Exception as e:
                    print(f"[Network Chaos] ERROR: Could not clean up manifest at {manifest_path}: {e}")
        elif self.target == 'docker':
            for container_id in self.applied_docker_chaos:
                self._cleanup_docker_network_rule(container_id, 'all')