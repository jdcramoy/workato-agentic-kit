declare module 'claude-code' {
  interface PluginState {
    'session-budget': { warned: boolean; blocks: number }
  }
}
