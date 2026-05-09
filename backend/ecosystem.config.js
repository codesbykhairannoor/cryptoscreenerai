module.exports = {
  apps: [
    {
      name: "MyTradingBot",
      script: "main.py",
      interpreter: "python",
      cwd: "C:\\Users\\Administrator\\cryptoscreenerai\\backend",

      // Restart policy
      restart_delay: 8000,          // Tunggu 8 detik sebelum restart (cukup untuk port dilepas)
      max_restarts: 10,
      min_uptime: "15s",
      exp_backoff_restart_delay: 3000,

      // Kill timeout — beri waktu 10 detik untuk graceful shutdown sebelum SIGKILL
      kill_timeout: 10000,

      // Environment — WAJIB set PYTHONUNBUFFERED supaya log langsung muncul
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
