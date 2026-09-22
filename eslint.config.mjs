import globals from "globals";

export default [{
  files: ["sdk/static/workbench/*.js"],
  languageOptions: {ecmaVersion: "latest", sourceType: "module", globals: globals.browser},
  rules: {"no-undef": "error", "no-unused-vars": ["error", {args: "none", caughtErrors: "none"}]}
}];
