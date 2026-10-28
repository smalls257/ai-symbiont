// QG-FE-03. html-validate rules: the recommended set minus pure style rules that generated
// reports trip without being invalid HTML (inline style, void-element style, doctype case).
export default {
  extends: ["html-validate:recommended"],
  rules: {
    "no-inline-style": "off",
    "prefer-native-element": "off",
    "void-style": "off",
    "doctype-style": "off",
  },
};
