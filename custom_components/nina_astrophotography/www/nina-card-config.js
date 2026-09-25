/**
 * Configuration shared by every card: the fallback prefix and the visual
 * editor's form, which Home Assistant renders from `getConfigForm()`.
 *
 * Not a card, so not in `frontend.py`'s `CARD_FILENAMES`.
 */

// Builds an entity id the registry cannot resolve: the slugified instance
// name, so `prefix:` is set for a renamed instance or a second rig.
export const DEFAULT_PREFIX = "n_i_n_a";

const RIG = {
  name: "device_id",
  label: "N.I.N.A. instance",
  helper: "Only needed with two or more N.I.N.A. instances. The hub or any of its equipment.",
  selector: { device: { filter: { integration: "nina_astrophotography" } } },
};

const FALLBACK = {
  type: "expandable",
  // Nameless, so `prefix` stays top-level instead of nesting under the section.
  name: "",
  title: "Entity id fallback",
  schema: [
    {
      name: "prefix",
      label: "Instance prefix",
      helper:
        "Builds the ids the registry cannot supply, such as the guider switch. "
        + "The instance name as it appears in entity ids; set it for a renamed "
        + "instance or a second rig.",
      default: DEFAULT_PREFIX,
      selector: { text: {} },
    },
  ],
};

/**
 * The form for a card whose own options are `fields`.
 *
 * `label` and `helper` are read back by `computeLabel`/`computeHelper`. `ha-form`
 * displays `default` but never saves it, and sends a cleared field as
 * `undefined`, so `setConfig` applies every default itself.
 */
export function configForm(fields = []) {
  return {
    schema: [RIG, ...fields, FALLBACK],
    computeLabel: (schema) => schema.label ?? schema.name,
    computeHelper: (schema) => schema.helper,
  };
}
