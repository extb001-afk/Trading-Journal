const path = require('path');
const ROOT = __dirname;
const PY = process.env.TJ_PYTHON || 'python3';

const base = {
  cwd: ROOT,
  interpreter: PY,
  env: { PYTHONUNBUFFERED: '1' },
  autorestart: true,
  exp_backoff_restart_delay: 2000,
  max_restarts: 1000,
  min_uptime: 30000,
  time: true,
};

const runner = unit => Object.assign({}, base, {
  name: 'tj-' + unit,
  script: path.join('src', 'unit_runner.py'),
  args: unit,
  treekill: false,
  kill_timeout: 35000,
});
const direct = (name, file) => Object.assign({}, base, {
  name,
  script: path.join('src', file),
  kill_timeout: 15000,
});

const apps = [
  runner('core'),
  runner('evm'),
  runner('sol'),
  runner('bsc'),
  runner('web'),
  direct('tj-ex', 'upbit_link.py'),
  direct('tj-exf', 'ex_foreign.py'),
  direct('tj-alert', 'alert_bot.py'),
];
if (process.env.TJ_ENABLE_REVIEW === '1') apps.push(direct('tj-review', 'review_daily.py'));

module.exports = { apps };
