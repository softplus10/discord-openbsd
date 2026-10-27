#include "navigation.h"
#include <QApplication>
#include <QAction>
#include <QDesktopServices>
#include <QDir>
#include <QMainWindow>
#include <QMessageBox>
#include <QStandardPaths>
#include <QStatusBar>
#include <QTimer>
#include <QWebEnginePage>
#include <QWebEngineProfile>
#include <QWebEngineSettings>
#include <QWebEngineView>
#include <QWebEngineFullScreenRequest>
#include <QWebEngineDownloadRequest>
#include <QtWebEngineCore/qtwebenginecoreglobal.h>

class DiscordPage final : public QWebEnginePage {
public:
    DiscordPage(QWebEngineProfile *profile, QObject *parent, bool popup = false)
        : QWebEnginePage(profile, parent), popup_(popup) {}
protected:
    bool acceptNavigationRequest(const QUrl &url, NavigationType, bool mainFrame) override {
        if (!mainFrame) return true;
        if (isAppUrl(url)) {
            if (popup_) {
                main_->setUrl(url);
                deleteLater();
                return false;
            }
            return true;
        }
        if (isExternalUrl(url)) QDesktopServices::openUrl(url);
        if (popup_) deleteLater();
        return false;
    }
    QWebEnginePage *createWindow(WebWindowType) override {
        auto *page = new DiscordPage(profile(), this, true);
        page->main_ = this;
        // Some popups are created without ever navigating.
        QTimer::singleShot(60000, page, &QObject::deleteLater);
        return page;
    }
private:
    bool popup_;
    QWebEnginePage *main_ = nullptr;
};

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    QApplication::setApplicationName("discord-openbsd");
    QApplication::setApplicationVersion(APP_VERSION);
    QApplication::setOrganizationName("softplus10");
    QMainWindow window;
    // Destroy the window/pages before the profile.
    auto *profile = new QWebEngineProfile("discord", &app);
    const auto storage = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    QDir().mkpath(storage);
    profile->setPersistentStoragePath(storage + "/web");
    profile->setCachePath(QStandardPaths::writableLocation(QStandardPaths::CacheLocation));
    profile->setPersistentCookiesPolicy(QWebEngineProfile::ForcePersistentCookies);
    auto *view = new QWebEngineView(&window);
    auto *page = new DiscordPage(profile, view);
    view->setPage(page);
    QObject::connect(page, &QWebEnginePage::urlChanged, page, [page](const QUrl &url) {
        // History API transitions do not call acceptNavigationRequest.
        if (!isAppUrl(url) && isExternalUrl(url)) {
            QDesktopServices::openUrl(url);
            page->setUrl(QUrl("https://discord.com/channels/@me"));
        }
    });
    page->settings()->setAttribute(QWebEngineSettings::JavascriptCanOpenWindows, true);
    page->settings()->setAttribute(QWebEngineSettings::FullScreenSupportEnabled, true);
    QObject::connect(page, &QWebEnginePage::fullScreenRequested,
                     &window, [&window](QWebEngineFullScreenRequest request) {
        request.accept();
        request.toggleOn() ? window.showFullScreen() : window.showNormal();
    });
    QObject::connect(page, &QWebEnginePage::featurePermissionRequested,
                     &window, [page, &window](const QUrl &origin, QWebEnginePage::Feature feature) {
        const bool supported = feature == QWebEnginePage::MediaAudioCapture
            || feature == QWebEnginePage::MediaVideoCapture
            || feature == QWebEnginePage::MediaAudioVideoCapture;
        bool allow = false;
        if (supported && origin.scheme() == "https" && origin.host() == "discord.com"
            && origin.port(443) == 443 && origin.userInfo().isEmpty())
            allow = QMessageBox::question(&window, "Discord permission",
                "Allow Discord to use your microphone/camera?") == QMessageBox::Yes;
        page->setFeaturePermission(origin, feature, allow ? QWebEnginePage::PermissionGrantedByUser
                                                       : QWebEnginePage::PermissionDeniedByUser);
    });
    QObject::connect(profile, &QWebEngineProfile::downloadRequested,
                     &window, [](QWebEngineDownloadRequest *download) {
        download->cancel();
        if (isExternalUrl(download->url())) QDesktopServices::openUrl(download->url());
    });
    QObject::connect(view, &QWebEngineView::loadFinished, &window, [&window](bool ok) {
        window.statusBar()->showMessage(ok ? QString() : "Discord failed to load. Check your connection and reload.");
    });
    auto *reload = new QAction("Reload", &window);
    reload->setShortcut(QKeySequence::Refresh);
    QObject::connect(reload, &QAction::triggered, view, &QWebEngineView::reload);
    window.addAction(reload);
    window.setCentralWidget(view);
    window.setWindowTitle(QString("Discord — %1 (Chromium %2)").arg(APP_VERSION, qWebEngineChromiumVersion()));
    window.resize(1200, 800);
    view->setUrl(QUrl("https://discord.com/channels/@me"));
    window.show();
    return app.exec();
}
