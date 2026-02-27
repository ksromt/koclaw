//! Persona system for AI identity management.
//!
//! Defines an AI persona's identity with per-channel behavior overrides.
//! The persona system prompt is injected into Agent requests so the LLM
//! behaves consistently across all channels.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::channel::ChannelType;

/// Defines an AI persona's identity and behavior.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Persona {
    /// Persona name (e.g., "Kokoron")
    pub name: String,
    /// Base system prompt shared across all channels
    pub base_prompt: String,
    /// Per-channel prompt overrides
    pub channel_prompts: Vec<ChannelPrompt>,
    /// Personality traits
    pub traits: Vec<String>,
    /// Preferred language for responses
    pub language: String,
}

/// Channel-specific prompt override.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelPrompt {
    pub channel: ChannelType,
    /// Additional prompt text appended to the base prompt for this channel
    pub prompt_suffix: String,
    /// Display name override for this channel
    pub display_name: Option<String>,
}

impl Persona {
    /// Get the full system prompt for a given channel.
    pub fn system_prompt(&self, channel: ChannelType) -> String {
        let mut prompt = self.base_prompt.clone();

        if let Some(cp) = self.channel_prompts.iter().find(|cp| cp.channel == channel) {
            prompt.push('\n');
            prompt.push_str(&cp.prompt_suffix);
        }

        prompt
    }

    /// Get the display name for a given channel.
    pub fn display_name(&self, channel: ChannelType) -> &str {
        self.channel_prompts
            .iter()
            .find(|cp| cp.channel == channel)
            .and_then(|cp| cp.display_name.as_deref())
            .unwrap_or(&self.name)
    }

    /// Create a default Kokoron persona.
    pub fn kokoron() -> Self {
        Self {
            name: "Kokoron".to_string(),
            base_prompt: concat!(
                "You are Kokoron, a helpful and friendly AI assistant. ",
                "You are knowledgeable, creative, and always willing to help. ",
                "You maintain a warm and approachable personality while being precise and thorough.",
            )
            .to_string(),
            channel_prompts: vec![ChannelPrompt {
                channel: ChannelType::WebPublic,
                prompt_suffix: "You are embedded in a blog. Keep responses concise and relevant to the blog's content. Do not execute tools or access private data.".to_string(),
                display_name: Some("Kokoron (Blog Assistant)".to_string()),
            }],
            traits: vec![
                "helpful".to_string(),
                "friendly".to_string(),
                "knowledgeable".to_string(),
            ],
            language: "auto".to_string(),
        }
    }

    /// Parse a `Persona` from a YAML string.
    ///
    /// The YAML uses human-readable channel name keys (e.g. "telegram", "web-public")
    /// which are mapped to `ChannelType` variants. Unknown channel names are skipped
    /// with a warning log.
    pub fn from_yaml(yaml: &str) -> Result<Self, String> {
        let raw: RawPersonaYaml =
            serde_yaml::from_str(yaml).map_err(|e| format!("YAML parse error: {e}"))?;

        let channel_prompts = raw
            .channel_prompts
            .unwrap_or_default()
            .into_iter()
            .filter_map(|(key, value)| {
                let channel = channel_type_from_str(&key)?;
                Some(ChannelPrompt {
                    channel,
                    prompt_suffix: value.prompt_suffix.unwrap_or_default(),
                    display_name: value.display_name,
                })
            })
            .collect();

        Ok(Self {
            name: raw.name.unwrap_or_else(|| "Kokoron".to_string()),
            base_prompt: raw.base_prompt.unwrap_or_default(),
            channel_prompts,
            traits: raw.traits.unwrap_or_default(),
            language: raw.language.unwrap_or_else(|| "auto".to_string()),
        })
    }
}

/// Intermediate YAML representation with all fields optional for graceful defaults.
#[derive(Deserialize)]
struct RawPersonaYaml {
    name: Option<String>,
    base_prompt: Option<String>,
    language: Option<String>,
    traits: Option<Vec<String>>,
    channel_prompts: Option<HashMap<String, RawChannelPrompt>>,
    // Fields consumed by Python agent only; ignored on the Rust side.
    #[allow(dead_code)]
    live2d: Option<serde_yaml::Value>,
    #[allow(dead_code)]
    voice: Option<serde_yaml::Value>,
}

#[derive(Deserialize)]
struct RawChannelPrompt {
    prompt_suffix: Option<String>,
    display_name: Option<String>,
}

/// Map a channel name string from YAML to a `ChannelType` enum variant.
fn channel_type_from_str(s: &str) -> Option<ChannelType> {
    match s {
        "telegram" => Some(ChannelType::Telegram),
        "qq" => Some(ChannelType::QQ),
        "discord" => Some(ChannelType::Discord),
        "websocket" => Some(ChannelType::WebSocket),
        "web-public" => Some(ChannelType::WebPublic),
        _ => {
            tracing::warn!(channel = s, "Unknown channel name in persona.yaml, skipping");
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_system_prompt_default() {
        let persona = Persona::kokoron();
        let prompt = persona.system_prompt(ChannelType::Telegram);
        assert!(prompt.contains("Kokoron"));
        // Telegram has no channel-specific override
        assert!(!prompt.contains("blog"));
    }

    #[test]
    fn test_system_prompt_with_channel_override() {
        let persona = Persona::kokoron();
        let prompt = persona.system_prompt(ChannelType::WebPublic);
        assert!(prompt.contains("Kokoron"));
        assert!(prompt.contains("blog"));
    }

    #[test]
    fn test_display_name_default() {
        let persona = Persona::kokoron();
        assert_eq!(persona.display_name(ChannelType::Telegram), "Kokoron");
    }

    #[test]
    fn test_display_name_override() {
        let persona = Persona::kokoron();
        assert_eq!(
            persona.display_name(ChannelType::WebPublic),
            "Kokoron (Blog Assistant)"
        );
    }

    #[test]
    fn test_from_yaml_full() {
        let yaml = r#"
name: "TestBot"
language: "en"
base_prompt: "You are TestBot."
traits:
  - smart
  - witty
channel_prompts:
  telegram:
    prompt_suffix: "Telegram suffix."
  web-public:
    prompt_suffix: "Blog suffix."
    display_name: "TestBot (Blog)"
live2d:
  model_path: "test.model3.json"
voice:
  tts_provider: "gpt_sovits"
"#;
        let persona = Persona::from_yaml(yaml).unwrap();
        assert_eq!(persona.name, "TestBot");
        assert_eq!(persona.language, "en");
        assert!(persona.base_prompt.contains("TestBot"));
        assert_eq!(persona.traits, vec!["smart", "witty"]);
        assert_eq!(persona.channel_prompts.len(), 2);

        let tg_prompt = persona.system_prompt(ChannelType::Telegram);
        assert!(tg_prompt.contains("Telegram suffix."));

        let web_prompt = persona.system_prompt(ChannelType::WebPublic);
        assert!(web_prompt.contains("Blog suffix."));
        assert_eq!(persona.display_name(ChannelType::WebPublic), "TestBot (Blog)");
    }

    #[test]
    fn test_from_yaml_minimal() {
        let yaml = "name: \"MinimalBot\"\n";
        let persona = Persona::from_yaml(yaml).unwrap();
        assert_eq!(persona.name, "MinimalBot");
        assert_eq!(persona.language, "auto");
        assert!(persona.channel_prompts.is_empty());
        assert!(persona.traits.is_empty());
    }

    #[test]
    fn test_from_yaml_unknown_channel_skipped() {
        let yaml = r#"
name: "Bot"
base_prompt: "Hello"
channel_prompts:
  unknown-channel:
    prompt_suffix: "Should be skipped."
  telegram:
    prompt_suffix: "Telegram here."
"#;
        let persona = Persona::from_yaml(yaml).unwrap();
        assert_eq!(persona.channel_prompts.len(), 1);
        assert_eq!(persona.channel_prompts[0].channel, ChannelType::Telegram);
    }

    #[test]
    fn test_from_yaml_invalid() {
        let yaml = "{{{{not valid yaml";
        let result = Persona::from_yaml(yaml);
        assert!(result.is_err());
    }
}
