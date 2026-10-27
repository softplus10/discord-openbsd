#include <QtWebEngineCore/qtwebenginecoreglobal.h>
#include <QJsonDocument>
#include <QJsonObject>
#include <cstdio>
int main() {
    const auto data = QJsonDocument(QJsonObject{
        {"chromium", qWebEngineChromiumVersion()},
        {"qt", qWebEngineVersion()}}).toJson(QJsonDocument::Compact);
    std::puts(data.constData());
}
