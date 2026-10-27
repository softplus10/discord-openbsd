#include "navigation.h"
#include <cstdio>
int main() {
    const QStringList internal = {
        "https://discord.com/channels/@me", "https://discord.com/channels/1/2",
        "https://discord.com/login?redirect_to=%2Fchannels%2F%40me",
        "https://discord.com/invite/abc", "https://discord.com/app",
        "https://discord.com:443/verify?token=abc"};
    const QStringList external = {
        "https://discord.com/", "https://discord.com/blog", "https://discord.com/developers",
        "https://discord.com/oauth2/authorize?client_id=1", "https://discord.com/download",
        "https://discord.com/login-evil", "https://discord.com/channels-evil",
        "https://discord.com.evil.test/channels/1", "https://evil.test/",
        "http://discord.com/channels/1", "https://discord.com:444/channels/1",
        "https://user@discord.com/channels/1", "file:///etc/passwd", "javascript:alert(1)",
        "https://discord.com/channels/%2e%2e/blog", "data:text/html,hello"};
    for (const auto &url : internal) if (!isAppUrl(QUrl(url))) {
        std::fprintf(stderr, "Rejected app URL: %s\n", qPrintable(url)); return 1;
    }
    for (const auto &url : external) if (isAppUrl(QUrl(url))) {
        std::fprintf(stderr, "Accepted non-app URL: %s\n", qPrintable(url)); return 1;
    }
    return 0;
}
