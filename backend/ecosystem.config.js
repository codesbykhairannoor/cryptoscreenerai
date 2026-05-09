module.exports = {
  apps: [
    {
      name: "MyTradingBot",
      script: "main.py",
      interpreter: "python",
      cwd: "C:\\Users\\Administrator\\cryptoscreenerai\\backend",

      // Restart policy — tunggu 5 detik sebelum restart supaya port lama dilepas
      restart_delay: 5000,
      max_restarts: 10,
      min_uptime: "10s",

      // Jangan restart kalau exit code 1 (port conflict) lebih dari 3x dalam 1 menit
      // Ini mencegah restart loop yang bikin log spam
      exp_backoff_restart_delay: 3000,

      // Environment
      env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
      },

      // Log
      out_file: "C:\\Users\\Administrator\\.pm2\\logs\\MyTradingBot-out.log",
      error_file: "C:\\Users\\Administrator\\.pm2\\logs\\MyTradingBot-error.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      merge_logs: true,
    },
  ],
};
