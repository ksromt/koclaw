use anyhow::Result;
use koclaw_common::channel::{BoxFuture, MessageRouter};
use koclaw_common::message::IncomingMessage;
use tracing::info;

/// Routes incoming messages from channels to the agent and back.
pub struct Router {
    // TODO: agent bridge connection
    // TODO: channel registry
}

impl Router {
    pub fn new() -> Self {
        Self {}
    }
}

impl MessageRouter for Router {
    fn route(&self, message: IncomingMessage) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            info!(
                channel = %message.channel,
                user = %message.user_id,
                "Routing message"
            );

            // TODO: Check permissions
            // TODO: Forward to agent
            // TODO: Return response through channel

            Ok(())
        })
    }
}
