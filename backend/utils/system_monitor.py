"""
System monitoring and metrics collection for comprehensive logging
"""
import psutil
import time
import threading
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import json
import os

logger = logging.getLogger(__name__)

class SystemMonitor:
    """Collects system metrics for logging"""
    
    def __init__(self, collect_interval: int = 60):
        self.collect_interval = collect_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
    def get_cpu_metrics(self) -> Dict[str, Any]:
        """Get CPU usage metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            return {
                'cpu_percent': cpu_percent,
                'cpu_count': cpu_count,
                'cpu_frequency_mhz': cpu_freq.current if cpu_freq else None,
                'cpu_per_core': psutil.cpu_percent(percpu=True)
            }
        except Exception as e:
            logger.error(f"Error collecting CPU metrics: {e}")
            return {'error': str(e)}
    
    def get_memory_metrics(self) -> Dict[str, Any]:
        """Get memory usage metrics"""
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            return {
                'memory_total_mb': round(memory.total / (1024 * 1024), 2),
                'memory_available_mb': round(memory.available / (1024 * 1024), 2),
                'memory_used_mb': round(memory.used / (1024 * 1024), 2),
                'memory_percent': memory.percent,
                'memory_cached_mb': round(memory.cached / (1024 * 1024), 2) if hasattr(memory, 'cached') else None,
                'swap_total_mb': round(swap.total / (1024 * 1024), 2),
                'swap_used_mb': round(swap.used / (1024 * 1024), 2),
                'swap_percent': swap.percent
            }
        except Exception as e:
            logger.error(f"Error collecting memory metrics: {e}")
            return {'error': str(e)}
    
    def get_disk_metrics(self) -> Dict[str, Any]:
        """Get disk usage metrics"""
        try:
            disk = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()
            
            return {
                'disk_total_gb': round(disk.total / (1024 * 1024 * 1024), 2),
                'disk_used_gb': round(disk.used / (1024 * 1024 * 1024), 2),
                'disk_free_gb': round(disk.free / (1024 * 1024 * 1024), 2),
                'disk_percent': disk.percent,
                'disk_read_bytes': disk_io.read_bytes if disk_io else None,
                'disk_write_bytes': disk_io.write_bytes if disk_io else None,
                'disk_read_count': disk_io.read_count if disk_io else None,
                'disk_write_count': disk_io.write_count if disk_io else None
            }
        except Exception as e:
            logger.error(f"Error collecting disk metrics: {e}")
            return {'error': str(e)}
    
    def get_network_metrics(self) -> Dict[str, Any]:
        """Get network usage metrics"""
        try:
            net_io = psutil.net_io_counters()
            
            return {
                'network_bytes_sent': net_io.bytes_sent,
                'network_bytes_recv': net_io.bytes_recv,
                'network_packets_sent': net_io.packets_sent,
                'network_packets_recv': net_io.packets_recv,
                'network_errin': net_io.errin,
                'network_errout': net_io.errout,
                'network_dropin': net_io.dropin,
                'network_dropout': net_io.dropout
            }
        except Exception as e:
            logger.error(f"Error collecting network metrics: {e}")
            return {'error': str(e)}
    
    def get_process_metrics(self) -> Dict[str, Any]:
        """Get current process metrics"""
        try:
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            
            return {
                'process_pid': current_process.pid,
                'process_name': current_process.name(),
                'process_status': current_process.status(),
                'process_cpu_percent': current_process.cpu_percent(),
                'process_memory_mb': round(current_process.memory_info().rss / (1024 * 1024), 2),
                'process_threads': current_process.num_threads(),
                'process_children_count': len(children),
                'process_uptime_seconds': time.time() - current_process.create_time()
            }
        except Exception as e:
            logger.error(f"Error collecting process metrics: {e}")
            return {'error': str(e)}
    
    def collect_all_metrics(self) -> Dict[str, Any]:
        """Collect all system metrics"""
        timestamp = datetime.utcnow().isoformat()
        
        metrics = {
            'timestamp': timestamp,
            'hostname': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
            'cpu': self.get_cpu_metrics(),
            'memory': self.get_memory_metrics(),
            'disk': self.get_disk_metrics(),
            'network': self.get_network_metrics(),
            'process': self.get_process_metrics()
        }
        
        return metrics
    
    def log_metrics(self):
        """Log collected metrics"""
        metrics = self.collect_all_metrics()
        logger.info(f"SYSTEM_METRICS: {json.dumps(metrics)}")
    
    def start_monitoring(self):
        """Start continuous monitoring"""
        if self.running:
            logger.warning("System monitor already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info(f"System monitoring started (interval: {self.collect_interval}s)")
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("System monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                self.log_metrics()
                time.sleep(self.collect_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.collect_interval)

# Global instance
system_monitor = SystemMonitor()

def start_system_monitoring():
    """Start system monitoring service"""
    system_monitor.start_monitoring()

def stop_system_monitoring():
    """Stop system monitoring service"""
    system_monitor.stop_monitoring()

def get_current_metrics() -> Dict[str, Any]:
    """Get current system metrics snapshot"""
    return system_monitor.collect_all_metrics()