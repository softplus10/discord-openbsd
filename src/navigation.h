#pragma once
#include <QUrl>
#include <QStringList>

// A top-level navigation policy. CDN, gateway, API and iframe traffic is
// intentionally unaffected; those requests are necessary for the web app.
inline bool isAppUrl(const QUrl &url) {
    if (!url.isValid() || url.scheme() != "https" || url.host() != "discord.com"
        || url.port(443) != 443 || !url.userInfo().isEmpty()) return false;
    const auto path = url.path(QUrl::FullyDecoded);
    if (path.contains('\\') || path.contains(QChar::Null)) return false;
    for (const auto &part : path.split('/'))
        if (part == "." || part == "..") return false;
    const QStringList roots = {"/app", "/channels", "/login", "/register",
        "/invite", "/verify", "/reset", "/reset-password", "/claim"};
    for (const auto &root : roots)
        if (path == root || path.startsWith(root + '/')) return true;
    return false;
}

inline bool isExternalUrl(const QUrl &url) {
    return url.isValid() && !url.host().isEmpty() && url.userInfo().isEmpty()
        && (url.scheme() == "https" || url.scheme() == "http");
}
