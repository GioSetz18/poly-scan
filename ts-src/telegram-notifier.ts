export class TelegramNotifier {
  constructor(
    private readonly botToken?: string,
    private readonly chatId?: string,
    private readonly dryRun = false
  ) {}

  async send(message: string): Promise<void> {
    if (this.dryRun) {
      console.log(message);
      return;
    }
    if (!this.botToken || !this.chatId) {
      throw new Error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required unless --dry-run is used");
    }
    const response = await fetch(`https://api.telegram.org/bot${this.botToken}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: this.chatId,
        text: message,
        disable_web_page_preview: true
      })
    });
    if (!response.ok) {
      throw new Error(`Telegram send failed: HTTP ${response.status}`);
    }
  }
}
