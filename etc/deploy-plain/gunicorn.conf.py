# Gunicorn configuration for OPTIMAP
# Copy to: /opt/optimap/gunicorn.conf.py

import multiprocessing

# Bind to Unix socket for nginx
bind = "unix:/opt/optimap/gunicorn.sock"

# Workers: (2 x CPU cores) + 1
# Adjust based on available memory and CPU
workers = multiprocessing.cpu_count() * 2 + 1

# Worker class
# Use 'sync' for standard workloads
# Use 'gevent' or 'eventlet' for high-concurrency async workloads
worker_class = "sync"

# Threads per worker (only relevant for gthread worker class)
threads = 1

# Timeout for worker processes (seconds)
# Increase for long-running requests (e.g., large file uploads)
timeout = 120

# Graceful timeout for worker restart
graceful_timeout = 30

# Keep-alive connections (seconds)
keepalive = 5

# Maximum requests per worker before restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "/opt/optimap/logs/gunicorn-access.log"
errorlog = "/opt/optimap/logs/gunicorn-error.log"
loglevel = "info"

# Access log format (similar to nginx combined format)
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "optimap-gunicorn"

# Working directory
chdir = "/opt/optimap/app"

# Preload application code before forking workers
# Reduces memory usage but may cause issues with some applications
preload_app = False

# Security limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Capture output to error log
capture_output = True

# Daemonize (set to False when using systemd)
daemon = False

# User and group (usually set in systemd service file instead)
# user = "optimap"
# group = "optimap"

# Umask for created files
umask = 0o007

# Temporary file directory
tmp_upload_dir = None
