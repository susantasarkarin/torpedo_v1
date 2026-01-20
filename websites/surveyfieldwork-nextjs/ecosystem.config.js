module.exports = {
  apps: [
    {
      name: 'surveyfieldwork-website',
      script: 'npm',
      args: 'start',
      cwd: '/var/www/surveyfieldwork-nextjs',
      instances: 'max',
      exec_mode: 'cluster',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production',
        PORT: 3001
      },
      env_production: {
        NODE_ENV: 'production',
        PORT: 3001,
        NEXT_PUBLIC_API_URL: 'http://localhost:8000',
        NEXT_PUBLIC_DOMAIN: 'surveyfieldwork.com'
      }
    }
  ]
};
