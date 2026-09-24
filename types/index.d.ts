// The session state jev-no-bullshit keeps: the text of replies the Jev check
// flagged, so their transcript rows draw as one withdrawn line; how many times its feedback has redirected this prompt, the feedback waiting
// for the turn to end, and the feedback it last submitted.
declare module "claude-code" {
  interface PluginState {
    "jev-no-bullshit": { withdrawn: string[]; redirects: number; pending: string; sent: string }
  }
}
