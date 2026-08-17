export function toSsnMessage(message) {
    const attachment = message.attachments.find(item => item.contentType?.startsWith("image/"));
    return {
        id: `discord-${message.id}`,
        chatname: message.member?.displayName || message.author.globalName || message.author.username,
        chatbadges: "",
        backgroundColor: "",
        textColor: "",
        chatmessage: message.cleanContent || message.content || "",
        chatimg: message.author.displayAvatarURL({ extension: "png", size: 128 }),
        nameColor: message.member?.displayHexColor === "#000000" ? "" : (message.member?.displayHexColor || ""),
        hasDonation: "",
        membership: "",
        contentimg: attachment?.url || "",
        textonly: true,
        type: "discord",
        userid: message.author.id,
        sourceName: message.guild?.name || "Discord",
        timestamp: Math.floor(message.createdTimestamp / 1000)
    };
}

export function toRelayText(payload) {
    return `${payload.chatname} said: ${payload.chatmessage || "shared an image"}`;
}
