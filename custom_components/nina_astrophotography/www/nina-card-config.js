/**
 * What every card shares about its configuration: the fallback prefix, and the
 * visual editor's form.
 *
 * Not a card, and not in `frontend.py`'s `CARD_FILENAMES` — see
 * `nina-entity-resolver.js`, which is imported the same way.
 *
 * A card's `static getConfigForm()` returns `configForm(...)`, and Home
 * Assistant renders the form itself; there is no editor element to define.
 */

// The fallback path, not the primary one: entity ids normally come from the
// registry (`_eid`), and the prefix is what an id is built from when a
// particular entity cannot be resolved. It is the instance name from the config
// flow, slugified — `N.I.N.A.` by default. Set `prefix:` for a renamed
// instance, or for the second rig.
export const DEFAULT_PREFIX = "n_i_n_a";

// Labels and helper text ride on the schema entries and are read back by
// `computeLabel`/`computeHelper`; `ha-form` ignores keys it does not know.
//
// Defaults go in `default`, which `ha-form` shows as a placeholder (a switch
// shows it as its position) but never writes: an untouched form leaves the YAML
// empty, and a cleared field comes back `undefined`. So every card applies its
// own defaults in `setConfig`, and must tolerate a key present but `undefined`.
const RIG = {
  name: "device_id",
  label: "N.I.N.A. device",
  helper: "Only needed with two or more N.I.N.A. instances. The hub or any of its equipment.",
  // The picker lists the hub and every piece of equipment, which all belong to
  // the one config entry; the resolver accepts any of them.
  selector: { device: { filter: { integration: "nina_astrophotography" } } },
};

const FALLBACK = {
  type: "expandable",
  // Nameless, so its field is stored at the top level rather than nested.
  name: "",
  title: "Entity id fallback",
  schema: [
    {
      name: "prefix",
      label: "Instance prefix",
      helper:
        "Builds the ids the registry cannot supply, such as the guider switch. "
        + "Set it for a renamed instance, or for a second rig.",
      default: DEFAULT_PREFIX,
      selector: { text: {} },
    },
  ],
};

/** The form for a card whose own options are `fields`. */
export function configForm(fields = []) {
  return {
    schema: [RIG, ...fields, FALLBACK],
    computeLabel: (schema) => schema.label ?? schema.name,
    computeHelper: (schema) => schema.helper,
  };
}
