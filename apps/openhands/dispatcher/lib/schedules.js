// Scheduling module — cron-like task scheduler
// Exports: initSchedules, handleScheduleCommand, runScheduleTick, getSchedules, saveSchedules, loadSchedules, computeNextRun, formatNextRun

import { writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export function initSchedules(statePath) {
  const schedules = new Map();
  let scheduleIdCounter = 0;
  const SCHEDULES_FILE = join(statePath, 'dispatcher-schedules.json');

  function save() {
    try {
      var data = [];
      for (const [id, s] of schedules) {
        data.push({
          id: s.id, chatId: s.chatId, cron: s.cron, task: s.task,
          createdAt: s.createdAt, lastRun: s.lastRun, nextRun: s.nextRun, enabled: s.enabled
        });
      }
      writeFileSync(SCHEDULES_FILE, JSON.stringify(data));
      if (scheduleIdCounter > 0) scheduleIdCounter = Math.max(scheduleIdCounter, ...Array.from(schedules.keys()).map(Number));
    } catch(e) {}
  }

  function load() {
    try {
      var raw = readFileSync(SCHEDULES_FILE, 'utf-8');
      var data = JSON.parse(raw);
      if (Array.isArray(data)) {
        data.forEach(function(s) {
          schedules.set(String(s.id), {
            id: s.id, chatId: s.chatId, cron: s.cron, task: s.task,
            createdAt: s.createdAt, lastRun: s.lastRun || null,
            nextRun: s.nextRun || computeNextRun(s.cron, Date.now()),
            enabled: s.enabled !== false
          });
          scheduleIdCounter = Math.max(scheduleIdCounter, s.id);
        });
        console.log('[schedules] loaded ' + data.length + ' schedules from disk');
      }
    } catch(e) {}
  }

  function computeNextRun(cronExpr, fromTime) {
    var now = fromTime || Date.now();
    var expr = (cronExpr || '').toLowerCase().trim();
    var everyMin = expr.match(/every\s+(\d+)\s*min/);
    if (everyMin) return now + parseInt(everyMin[1]) * 60000;
    var everyHr = expr.match(/every\s+(\d+)\s*hour/);
    if (everyHr) return now + parseInt(everyHr[1]) * 3600000;
    if (expr === 'hourly') return now + 3600000;
    var dailyTime = expr.match(/daily\s*(?:at\s*)?(\d{1,2}):?(\d{2})?/);
    if (dailyTime || expr === 'daily') {
      var h = dailyTime ? parseInt(dailyTime[1]) : 9;
      var m = dailyTime && dailyTime[2] ? parseInt(dailyTime[2]) : 0;
      var d = new Date(now);
      d.setHours(h, m, 0, 0);
      if (d.getTime() <= now) d.setDate(d.getDate() + 1);
      return d.getTime();
    }
    if (expr.startsWith('every')) return now + 300000;
    return now + 1800000;
  }

  function formatNextRun(timestamp) {
    if (!timestamp) return 'not scheduled';
    var diff = timestamp - Date.now();
    if (diff < 0) return 'overdue';
    var mins = Math.round(diff / 60000);
    if (mins < 60) return 'in ' + mins + ' min';
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return 'in ' + hrs + ' hr';
    var days = Math.round(hrs / 24);
    return 'in ' + days + ' day' + (days > 1 ? 's' : '');
  }

  function handleScheduleCommand(message, chatId, dispatchFn) {
    var parts = message.trim().split(/\s+/);
    if (parts[0] !== '/schedule') return null;
    var sub = (parts[1] || '').toLowerCase();

    if (sub === 'list' || sub === 'ls') {
      var userSchedules = [];
      for (const [id, s] of schedules) {
        if (String(s.chatId) === String(chatId) || s.chatId === chatId) {
          userSchedules.push(s);
        }
      }
      if (userSchedules.length === 0) return { type: 'direct', text: 'No scheduled tasks. Use:\n<code>/schedule add "every 5 minutes" "your task here"</code>' };
      var list = '<b>Scheduled Tasks (' + userSchedules.length + ')</b>\n\n';
      userSchedules.forEach(function(s, i) {
        var status = s.enabled ? '[on]' : '[off]';
        list += status + ' <b>#' + s.id + '</b> — ' + s.cron + '\n';
        list += '   Task: ' + (s.task.length > 60 ? s.task.slice(0,57)+'...' : s.task) + '\n';
        list += '   Next: ' + formatNextRun(s.nextRun);
        if (s.lastRun) {
          var ago = Math.round((Date.now() - s.lastRun) / 60000);
          list += ' | Last: ' + (ago < 1 ? 'just now' : ago + 'm ago');
        }
        list += '\n\n';
      });
      list += '<i>Delete with: /schedule delete &lt;id&gt;</i>';
      return { type: 'direct', text: list };
    }

    if (sub === 'delete' || sub === 'remove' || sub === 'rm') {
      var delId = parts[2];
      if (!delId) return { type: 'direct', text: '[warn] Usage: <code>/schedule delete &lt;id&gt;</code>\nUse /schedule list to see IDs.' };
      var s = schedules.get(delId);
      if (!s) return { type: 'direct', text: '[err] Schedule #' + delId + ' not found.' };
      if (String(s.chatId) !== String(chatId)) return { type: 'direct', text: '[err] Schedule #' + delId + ' belongs to another user.' };
      schedules.delete(delId);
      save();
      return { type: 'direct', text: '[done] Schedule #' + delId + ' deleted: <i>' + s.task.slice(0,80) + '</i>' };
    }

    if (sub === 'add' || sub === 'new' || sub === 'create') {
      parts.shift(); parts.shift();
    } else {
      parts.shift();
    }

    var rest = parts.join(' ');
    var match = rest.match(/^"([^"]+)"\s+"([^"]+)"/);
    if (!match) match = rest.match(/^'([^']+)'\s+'([^']+)'/);
    if (!match) {
      return { type: 'direct', text: '[warn] Usage:\n<code>/schedule add "every 5 minutes" "your task"</code>\n<code>/schedule add "daily 09:00" "morning report"</code>\n<code>/schedule add "hourly" "check status"</code>\n\nExamples:\n• every 30 minutes\n• every 2 hours\n• hourly\n• daily 09:00\n• daily' };
    }

    var cronExpr = match[1];
    var task = match[2];
    scheduleIdCounter++;
    var newId = String(scheduleIdCounter);
    var nextRun = computeNextRun(cronExpr, Date.now());

    schedules.set(newId, {
      id: newId, chatId: chatId, cron: cronExpr, task: task,
      createdAt: Date.now(), lastRun: null, nextRun: nextRun, enabled: true
    });
    save();

    return { type: 'direct', text: '<b>Schedule #' + newId + ' created!</b>\n\n' + cronExpr + '\n' + task + '\nNext run: ' + formatNextRun(nextRun) + '\n\n<i>Use /schedule list to view all schedules</i>' };
  }

  function runTick(dispatchFn) {
    var now = Date.now();
    for (const [id, s] of schedules) {
      if (!s.enabled) continue;
      if (s.nextRun && s.nextRun <= now) {
        console.log('[schedule] firing #' + id + ' for chatId=' + s.chatId + ' task="' + s.task.slice(0,50) + '"');
        s.lastRun = now;
        s.nextRun = computeNextRun(s.cron, now);
        if (dispatchFn) {
          dispatchFn(s.chatId, s.task).catch(function(e) {
            console.error('[schedule] error firing #' + id + ':', e.message);
          });
        }
      }
    }
  }

  // Load persisted schedules on init
  load();

  return { schedules, save, load, handleScheduleCommand, runTick, computeNextRun, formatNextRun, scheduleIdCounter };
}
