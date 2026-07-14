import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopApi, DesktopState, ProviderId, ProviderStatus, TerminalMetadata } from '../shared/types';

function subscribe<T>(channel: string, listener: (payload: T) => void): () => void { const handler = (_event: Electron.IpcRendererEvent, payload: T) => listener(payload); ipcRenderer.on(channel, handler); return () => ipcRenderer.removeListener(channel, handler); }
const api: DesktopApi = {
  state: { get: () => ipcRenderer.invoke('state:get'), update: (patch: Partial<Pick<DesktopState, 'workspace' | 'selectedProvider'>>) => ipcRenderer.invoke('state:update', patch) },
  provider: { show: (id: ProviderId) => ipcRenderer.invoke('provider:show', id), hide: () => ipcRenderer.invoke('provider:hide'), action: (id, action) => ipcRenderer.invoke('provider:action', id, action), clearSession: (id) => ipcRenderer.invoke('provider:clear-session', id), setBounds: (bounds) => ipcRenderer.send('provider:set-bounds', bounds), onStatus: (listener: (status: ProviderStatus) => void) => subscribe('provider:status', listener) },
  terminal: { list: () => ipcRenderer.invoke('terminal:list'), chooseDirectory: () => ipcRenderer.invoke('terminal:choose-directory'), create: (input) => ipcRenderer.invoke('terminal:create', input), write: (id, data) => ipcRenderer.send('terminal:write', id, data), resize: (id, cols, rows) => ipcRenderer.send('terminal:resize', id, cols, rows), kill: (id) => ipcRenderer.invoke('terminal:kill', id), clearHistory: (id) => ipcRenderer.invoke('terminal:clear-history', id), recordCommand: (id, command) => ipcRenderer.invoke('terminal:record-command', id, command), onData: (listener: (payload: { id: string; data: string }) => void) => subscribe('terminal:data', listener), onState: (listener: (terminal: TerminalMetadata) => void) => subscribe('terminal:state', listener) },
};
contextBridge.exposeInMainWorld('wardenDesk', api);
