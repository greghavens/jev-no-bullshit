// The session state jev-no-bullshit keeps: how many times its feedback has
// redirected this prompt, the feedback waiting for the turn to end, and the
// last turn the person typed a prompt over.
declare module "claude-code" {
  interface PluginState {
    "jev-no-bullshit": { redirects: number; pending: string; superseded: string }
  }
}
