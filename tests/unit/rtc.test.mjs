// The browser's half of remote access security: it only accepts an answer signed by the
// host key in the link, over exactly the offer it sent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bundledCandidates, fromB64url, hostIdFor, toB64url, verifyAnswer } from '../../web/rtc.js';

async function hostKey() {
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
  const sign = async (offer, answer) =>
    toB64url(new Uint8Array(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey,
      new TextEncoder().encode(`glass-rtc-v1\n${offer}\n--\n${answer}`))));
  return { key: toB64url(raw), sign };
}

test('base64url round-trips', () => {
  const bytes = Uint8Array.from({ length: 70 }, (_, i) => (i * 37) & 255);
  assert.deepEqual(fromB64url(toB64url(bytes)), bytes);
  assert.equal(toB64url(new Uint8Array([0xfb, 0xff])), '-_8'); // same as the host's encoder
});

test('host id is the first 16 bytes of SHA-256 of the key', async () => {
  const { key } = await hostKey();
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', fromB64url(key)));
  assert.equal(await hostIdFor(key), toB64url(digest.slice(0, 16)));
});

test('accepts a genuine answer and rejects tampering or another key', async () => {
  const host = await hostKey();
  const other = await hostKey();
  const sig = await host.sign('offer-sdp', 'answer-sdp');
  assert.equal(await verifyAnswer(host.key, 'offer-sdp', 'answer-sdp', sig), true);
  assert.equal(await verifyAnswer(host.key, 'offer-sdp', 'answer-sdp-swapped', sig), false, 'answer swapped in the middle');
  assert.equal(await verifyAnswer(host.key, 'other-offer', 'answer-sdp', sig), false, 'replayed for another offer');
  assert.equal(await verifyAnswer(other.key, 'offer-sdp', 'answer-sdp', sig), false, 'signed by a different key');
  assert.equal(await verifyAnswer(host.key, 'offer-sdp', 'answer-sdp', 'garbage'), false);
});

test('an offer lists its candidates once, on the bundle\'s first m-line', () => {
  const cand = (n) => `a=candidate:${n} 1 udp 2122260223 192.168.1.${n} 5000${n} typ host`;
  const m = (mid, kind) => [`m=${kind} 9 UDP/DTLS/SCTP webrtc-datachannel`, `a=mid:${mid}`, cand(1), cand(2), 'a=end-of-candidates'];
  const offer = (group) => ['v=0', 's=-', `a=group:BUNDLE ${group}`, ...m('0', 'application'), ...m('1', 'video'), ...m('2', 'video'), ''].join('\r\n');
  const out = bundledCandidates(offer('0 1 2'));
  const sections = out.split('\r\nm=');
  assert.equal(sections[1].match(/a=candidate:/g).length, 2);
  assert.match(sections[1], /a=end-of-candidates/);
  for (const s of sections.slice(2)) assert.doesNotMatch(s, /a=candidate:|a=end-of-candidates/);
  assert.ok(out.endsWith('\r\n'), 'keeps the final line break');
  // The bundle's first mid, wherever that m-line is.
  const tagged = bundledCandidates(offer('2 0 1')).split('\r\nm=');
  assert.equal(tagged[3].match(/a=candidate:/g).length, 2);
  assert.doesNotMatch(tagged[1], /a=candidate:/);
  // An m-line outside the bundle has its own transport: left alone.
  assert.equal(bundledCandidates(offer('0 1')), offer('0 1'));
});
