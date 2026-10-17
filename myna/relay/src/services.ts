// services.ts: numbers answered by the relay itself. A text to one of them never reaches another phone.
// A service gets the payload as the phone sent it (it is never encrypted: the relay is the other end).
// SPDX-License-Identifier: MIT

export interface Service {
  number: string;
  name: string;
  enabled: boolean;
  notice: string;                 // shown by the page next to the number
}

export const ECHO = '3246';       // E-C-H-O on the keys
export const CLAUDE = '252833';   // C-L-A-U-D-E on the keys

export const SERVICES: Service[] = [
  { number: ECHO, name: 'echo', enabled: true, notice: 'Sends your text back to you.' },
  // ---- DISABLED STUB ---------------------------------------------------------------------------------------------
  // A number answered by the Claude API. NOT BUILT: `enabled` is false, so the number is "unknown" to everyone, and
  // answerClaude() below calls nothing. Before this is switched on it needs, in this order:
  //   1. the owner's API key as a secret (wrangler secret put ANTHROPIC_API_KEY), never in the page or the repository;
  //   2. its own strict limits, apart from the text limits: texts per number and hour, and a daily cap for the whole
  //      network kept in the control object (when the cap is reached the number answers "closed for today");
  //   3. the notice below shown by the page BEFORE the first text, because a text to this number leaves the network:
  //      the relay must read it (it is not end-to-end encrypted) and sends it to Anthropic;
  //   4. the text itself is needed here, so the relay has to read the SMS-SUBMIT (3GPP TS 23.040 and
  //      23.038: 7-bit and UCS-2 text, long messages in parts) and write SMS-SUBMITs for the answer;
  //   5. nothing of the conversation stored: either no memory at all, or the last few texts kept by the PHONE and
  //      sent along.
  { number: CLAUDE, name: 'claude', enabled: false, notice: 'Texts to this number leave the network: they are read by the relay and answered by an AI (Claude, by Anthropic).' },
  // -----------------------------------------------------------------------------------------------------------------
];

export const service = (number: string) => SERVICES.find(s => s.number === number && s.enabled);

/** What a service answers: the payloads delivered back to the sender, each as a text from the service's number.
 *  The receiving client turns an SMS-SUBMIT into an SMS-DELIVER whatever its destination field says. */
export async function answer(s: Service, body: string): Promise<string[]> {
  if (s.name === 'echo') return [body];
  if (s.name === 'claude') return answerClaude(body);
  return [];
}

// DISABLED STUB: see the list above. Deliberately no fetch() here.
async function answerClaude(_body: string): Promise<string[]> {
  return [];
}
