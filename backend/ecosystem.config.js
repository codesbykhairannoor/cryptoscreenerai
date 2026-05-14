module.exports = {
  apps: [
    {
      name: "MyTradingBot",

      // Jalankan uvicorn langsung - lebih reliable di Windows
      // PM2 bisa kill process ini dengan benar saat restart
      script: "uvicorn",
      args: "main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5",
      interpreter: "none",
      cwd: "C:\\Users\\Administrator\\cryptoscreenerai\\backend",

      // Restart policy
      restart_delay: 8000,
      max_restarts: 10,
      min_uptime: "15s",
      exp_backoff_restart_delay: 3000,
      kill_timeout: 10000,

      // Environment
      env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
        PYTHONUTF8: "1",
      },

      // Log
      out_file:        "C:\\Users\\Administrator\\.pm2\\logs\\MyTradingBot-out.log",
      error_file:      "C:\\Users\\Administrator\\.pm2\\logs\\MyTradingBot-error.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      merge_logs:      true,
    },
  ],
};

