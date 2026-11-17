//! Highlights `<pre data-lang="...">` blocks in HTML files in place.
use std::{env, fs, process::ExitCode, sync::Arc};

use arborium::advanced::{CompiledGrammar, GrammarConfig};
use arborium::lang_clojure;

const OPEN: &str = "<pre data-lang=\"";
const CLOSE: &str = "</pre>";

// The bundled Clojure query only marks literals; also mark special forms and call heads.
const CLOJURE_EXTRA: &str = r#"
(list_lit . (sym_lit) @function)
((sym_lit) @keyword
  (#match? @keyword "^(def|defn|defn-|defmacro|fn|let|loop|recur|if|do|when|cond|ns|try|catch|finally|throw)$"))
"#;

fn highlighter() -> Result<arborium::Highlighter, String> {
    let query = format!("{}{CLOJURE_EXTRA}", lang_clojure::HIGHLIGHTS_QUERY);
    let grammar = CompiledGrammar::new(GrammarConfig {
        language: lang_clojure::language().into(),
        highlights_query: &query,
        injections_query: lang_clojure::INJECTIONS_QUERY,
        locals_query: lang_clojure::LOCALS_QUERY,
    })
    .map_err(|e| format!("clojure query: {e}"))?;
    let store = Arc::new(arborium::GrammarStore::new());
    store.insert("clojure", Arc::new(grammar));
    Ok(arborium::Highlighter::with_store(store))
}

fn unescape(text: &str) -> String {
    text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&amp;", "&")
}

fn highlight_blocks(html: &str, highlighter: &mut arborium::Highlighter) -> Result<String, String> {
    let mut out = String::with_capacity(html.len() * 2);
    let mut rest = html;
    while let Some(start) = rest.find(OPEN) {
        let after_attr = &rest[start + OPEN.len()..];
        let lang_end = after_attr.find('"').ok_or("unterminated data-lang")?;
        let lang = &after_attr[..lang_end];
        let body_start = after_attr[lang_end..].find('>').ok_or("unterminated <pre>")? + lang_end + 1;
        let body = &after_attr[body_start..];
        let body_end = body.find(CLOSE).ok_or("missing </pre>")?;
        let code = unescape(&body[..body_end]);
        let highlighted = highlighter.highlight(lang, &code).map_err(|e| format!("{lang}: {e}"))?;
        out.push_str(&rest[..start + OPEN.len()]);
        out.push_str(&after_attr[..body_start]);
        out.push_str(&highlighted);
        out.push_str(CLOSE);
        rest = &body[body_end + CLOSE.len()..];
    }
    out.push_str(rest);
    Ok(out)
}

fn main() -> ExitCode {
    let mut highlighter = match highlighter() {
        Ok(highlighter) => highlighter,
        Err(error) => {
            eprintln!("site-highlight: {error}");
            return ExitCode::FAILURE;
        }
    };
    for path in env::args().skip(1) {
        let result = fs::read_to_string(&path)
            .map_err(|e| e.to_string())
            .and_then(|html| highlight_blocks(&html, &mut highlighter))
            .and_then(|html| fs::write(&path, html).map_err(|e| e.to_string()));
        if let Err(error) = result {
            eprintln!("site-highlight: {path}: {error}");
            return ExitCode::FAILURE;
        }
    }
    ExitCode::SUCCESS
}
