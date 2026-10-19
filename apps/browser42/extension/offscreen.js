const BROKER_URL = 'ws://127.0.0.1:8765';
let socket;
let workerPort;

function connectWorker() {
  workerPort = chrome.runtime.connect({ name: 'browser42-offscreen' });
  workerPort.onMessage.addListener((result) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(result));
  });
  workerPort.onDisconnect.addListener(() => setTimeout(connectWorker, 100));
}

function connect() {
  if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;
  socket = new WebSocket(BROKER_URL);
  socket.onopen = () => socket.send(JSON.stringify({ role: 'extension' }));
  socket.onmessage = (event) => {
    const command = JSON.parse(event.data);
    workerPort.postMessage(command);
  };
  socket.onclose = () => setTimeout(connect, 1000);
  socket.onerror = () => socket.close();
}

connectWorker();
connect();