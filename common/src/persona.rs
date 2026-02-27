//! Persona system for AI identity management.
//!
//! Defines an AI persona's identity with per-channel behavior overrides.
//! The persona system prompt is injected into Agent requests so the LLM
//! behaves consistently across all channels.

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
}
