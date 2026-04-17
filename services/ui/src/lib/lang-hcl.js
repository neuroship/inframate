import { StreamLanguage } from "@codemirror/language";

const hclLanguage = StreamLanguage.define({
  startState() {
    return { inBlockComment: false, inString: false };
  },

  token(stream, state) {
    // Block comment
    if (state.inBlockComment) {
      if (stream.match("*/")) {
        state.inBlockComment = false;
      } else {
        stream.next();
      }
      return "blockComment";
    }

    // Whitespace
    if (stream.eatSpace()) return null;

    // Block comment start
    if (stream.match("/*")) {
      state.inBlockComment = true;
      return "blockComment";
    }

    // Line comments
    if (stream.match("//") || stream.match("#")) {
      stream.skipToEnd();
      return "lineComment";
    }

    // Heredoc
    if (stream.match(/<<-?\w+/)) {
      return "string";
    }

    // Strings with interpolation awareness
    if (stream.peek() === '"') {
      stream.next();
      while (!stream.eol()) {
        const ch = stream.next();
        if (ch === "\\") {
          stream.next();
          continue;
        }
        if (ch === "$" && stream.peek() === "{") {
          // Don't consume the interpolation marker, just mark the string part
          continue;
        }
        if (ch === '"') break;
      }
      return "string";
    }

    // Numbers
    if (stream.match(/^0x[0-9a-fA-F]+/) || stream.match(/^\d+(\.\d+)?([eE][+-]?\d+)?/)) {
      return "number";
    }

    // Booleans and null
    if (stream.match(/^(true|false|null)\b/)) {
      return "atom";
    }

    // Top-level block types (Terraform keywords)
    if (
      stream.match(
        /^(resource|data|variable|output|module|provider|terraform|locals|moved|import|check)\b/,
      )
    ) {
      return "keyword";
    }

    // Built-in meta-arguments
    if (
      stream.match(
        /^(for_each|count|depends_on|lifecycle|provisioner|connection|dynamic|content|source|version|required_providers|required_version|backend)\b/,
      )
    ) {
      return "keyword";
    }

    // Built-in functions (common ones)
    if (
      stream.match(
        /^(lookup|merge|concat|join|split|length|element|keys|values|flatten|distinct|toset|tolist|tomap|tonumber|tostring|tobool|try|can|file|templatefile|jsonencode|jsondecode|yamlencode|yamldecode|base64encode|base64decode|format|formatlist|replace|regex|regexall|substr|upper|lower|title|trimspace|trim|trimprefix|trimsuffix|startswith|endswith|contains|index|range|zipmap|map|list|set|coalesce|coalescelist|compact|chunklist|cidrhost|cidrnetmask|cidrsubnet|max|min|ceil|floor|abs|log|pow|signum|parseint|timestamp|timeadd|formatdate|uuid|bcrypt|md5|sha1|sha256|sha512|base64sha256|base64sha512|pathexpand|dirname|basename|abspath|fileexists|fileset|filebase64|one|alltrue|anytrue|sum|transpose|matchkeys|setintersection|setproduct|setsubtract|setunion|nonsensitive|sensitive|plantimestamp)\s*\(/,
      )
    ) {
      stream.backUp(1); // don't consume the paren
      return "variableName.function";
    }

    // Type keywords
    if (stream.match(/^(string|number|bool|list|map|set|object|tuple|any|optional)\b/)) {
      return "typeName";
    }

    // Interpolation ${ ... }
    if (stream.match("${")) {
      return "punctuation";
    }

    // Operators
    if (stream.match(/^[=!<>]=?/) || stream.match(/^[+\-*/%]/) || stream.match(/^&&|\|\|/)) {
      return "operator";
    }

    // Punctuation
    if (stream.match(/^[{}()\[\].,?:]/)) {
      return "punctuation";
    }

    // Arrows
    if (stream.match("=>")) {
      return "operator";
    }

    // Identifiers — attribute names before = are "property", others are "variable"
    if (stream.match(/^[a-zA-Z_][a-zA-Z0-9_-]*/)) {
      // Peek ahead for = to detect attribute assignment
      if (stream.match(/\s*=/, false)) {
        return "propertyName";
      }
      return "variableName";
    }

    stream.next();
    return null;
  },
});

export { hclLanguage };
