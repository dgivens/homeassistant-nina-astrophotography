/**
 * Rig states for `nina-livestack-card`, composed out of the committed dump.
 *
 * No image bytes are in the corpus, so every load fails and the card shows
 * that it could not load the stack. What the scenarios reach is everything
 * around the picture — the chips, the header, the start/stop button — and, in
 * `ops.mjs`, the paths the card signs: which stack, at what width, and which
 * update makes it fetch again.
 *
 * `dawn_flats` is dumped from inside its own night: six stacks over four
 * targets, NGC 281's S the newest, and the live stack stopped by dawn.
 * `site_configured` is dumped on a later day than its night, so it holds no
 * stack this session, with the live stack running.
 */

import { linkScenarios, rig } from "../hass.mjs";

const NIGHT = "dawn_flats";
const LIVESTACK = "image.n_i_n_a_livestack";

// The night with its `stacks` replaced: the row's own state and other
// attributes kept, so only the list differs.
const withStacks = (dump, edit) => {
  const row = dump[NIGHT].states[LIVESTACK];
  return rig(dump, NIGHT).override(LIVESTACK, row.state, {
    ...row.attributes,
    stacks: edit(row.attributes.stacks),
  });
};

export const scenarios = {
  // Every id resolved; the newest stack (NGC 281's S) shown, its one filter
  // chipped beside Latest, and the four targets above them.
  night: { hass: (dump) => rig(dump, NIGHT).build() },

  // The same rig with no registry, which is the prefix fallback. Must match
  // `night`.
  templated: { hass: (dump) => rig(dump, NIGHT).unresolvable().build() },

  // Not following: the stack first shown stays when another updates.
  pinned: {
    hass: (dump) => withStacks(dump, (stacks) => stacks.slice(1)).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    config: { follow_latest: false },
  },

  // NGC 281's S updated again: following, the card signs the stack anew.
  updated: {
    hass: (dump) => withStacks(dump, (stacks) => [
      { ...stacks[0], count: stacks[0].count - 1, updated: "2026-09-04T04:15:00-05:00" },
      ...stacks.slice(1),
    ]).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
  },

  // No capture holds a colour stack, so this one is invented: the plugin
  // counts a colour stack per channel and sends no `count`. The filter's name
  // is one the card cannot read colour from; the counts alone decide.
  colour: {
    hass: (dump) => withStacks(dump, (stacks) => [
      {
        ...stacks[0],
        filter: "F1",
        monochrome: false,
        count: null,
        red_count: 12,
        green_count: 12,
        blue_count: null,
      },
      ...stacks.slice(1),
    ]).build(),
  },

  // Folded to its header, which keeps the session's count, the badge and
  // start/stop: no stack is signed, even when the stack shown updates.
  folded: {
    hass: (dump) => rig(dump, NIGHT).build(),
    after: (dump) => [withStacks(dump, (stacks) => [
      { ...stacks[0], count: stacks[0].count + 1, updated: "2026-09-04T04:40:00-05:00" },
      ...stacks.slice(1),
    ]).build()],
    folded: ["card"],
  },

  // Without start/stop.
  no_controls: { hass: (dump) => rig(dump, NIGHT).build(), config: { show_controls: false } },

  // Running, with no stack this session: the empty state, and Stop offered.
  no_stacks: { hass: (dump) => rig(dump, "site_configured").build() },

  // The drivers down, and no stack ever: no image entity at all.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },

  // The lost link: the badge names it, and no command is offered.
  ...linkScenarios(),
};
