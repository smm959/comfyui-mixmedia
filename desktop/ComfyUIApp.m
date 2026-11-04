// Окно приложения ComfyUI MixMedia: WKWebView в своём NSWindow, без браузера.
//
// Собирается в make_installer.sh:
//   clang -fobjc-arc -framework Cocoa -framework WebKit -O2 desktop/ComfyUIApp.m -o ComfyUIApp
// Лаунчер передаёт адрес сервера и путь к иконке:
//   ComfyUIApp http://127.0.0.1:8188 /Applications/.../app.icns
//
// MIXMEDIA_SELFTEST=1 — самопроверка: окно, ресайз, снимок в /tmp/mixmedia-selftest.
// MIXMEDIA_HOME_WORKFLOW=имя — какой воркфлоу открывать при старте (по умолчанию
//   photostudio_mixmedia: comfyui/user/default/workflows/photostudio_mixmedia.json).
//
// WKWebView сам по себе НЕ показывает диалог выбора файла: если делегат не реализует
// webView:runOpenPanelWithParameters:…, любой <input type=file> молча ничего не делает.
// Поэтому здесь есть runOpenPanel (NSOpenPanel), JS alert/confirm/prompt и загрузки.

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

static NSString *const kFrameKey = @"mixmediaWindowFrame";
static NSString *const kDefaultURL = @"http://127.0.0.1:8188";
static NSString *const kDefaultHomeWorkflow = @"photostudio_mixmedia";
static NSString *const kSelftestDir = @"/tmp/mixmedia-selftest";

static NSString *WaitingPage(void) {
    return @"<!doctype html><meta charset=\"utf-8\">"
           "<body style=\"margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
           "background:#202020;color:#e6e6e6;font:15px -apple-system,Helvetica\">"
           "<div style=\"text-align:center\">"
           "<div style=\"font-size:19px;margin-bottom:10px\">ComfyUI MixMedia</div>"
           "<div style=\"opacity:.65\">поднимаю сервер…</div></div></body>";
}

static NSString *FailedPage(NSString *log) {
    return [NSString stringWithFormat:
            @"<!doctype html><meta charset=\"utf-8\">"
             "<body style=\"margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
             "background:#202020;color:#e6e6e6;font:15px -apple-system,Helvetica\">"
             "<div style=\"text-align:center;max-width:520px;line-height:1.5\">"
             "<div style=\"font-size:19px;margin-bottom:10px\">Сервер не поднялся</div>"
             "<div style=\"opacity:.65\">Лог: %@</div></div></body>", log];
}

@interface AppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate,
                                  WKUIDelegate, WKDownloadDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *web;
@property(nonatomic, strong) NSString *url;
@property(nonatomic, strong) NSString *logPath;
@property(nonatomic, strong) NSString *homeWorkflow;
@property(nonatomic, strong) NSMutableDictionary *measure;
@property(nonatomic, assign) BOOL loaded;
@property(nonatomic, assign) BOOL selftest;
@property(nonatomic, assign) BOOL homeLoaded;
@end

@implementation AppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)note {
    self.url = [[NSProcessInfo processInfo] environment][@"MIXMEDIA_URL"] ?: kDefaultURL;
    NSArray *args = [[NSProcessInfo processInfo] arguments];
    if (args.count > 1) self.url = args[1];

    NSString *icon = args.count > 2 ? args[2] : @"";
    if (icon.length && [[NSFileManager defaultManager] fileExistsAtPath:icon]) {
        [NSApp setApplicationIconImage:[[NSImage alloc] initWithContentsOfFile:icon]];
    }

    self.logPath = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/ComfyUI Mix Media.log"];
    self.measure = [NSMutableDictionary dictionary];
    self.selftest = [[[NSProcessInfo processInfo] environment][@"MIXMEDIA_SELFTEST"] isEqualToString:@"1"];
    self.homeWorkflow = [[NSProcessInfo processInfo] environment][@"MIXMEDIA_HOME_WORKFLOW"]
                            ?: kDefaultHomeWorkflow;

    [self buildMenu];
    [self buildWindow];

    if (self.selftest) [self startSelftest];
}

- (void)buildMenu {
    NSMenu *bar = [[NSMenu alloc] init];
    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [appItem setTitle:@"ComfyUI MixMedia"];
    [bar addItem:appItem];
    [NSApp setMainMenu:bar];

    NSMenu *appMenu = [[NSMenu alloc] init];
    [appItem setSubmenu:appMenu];
    [appMenu addItemWithTitle:@"О программе ComfyUI MixMedia"
                      action:@selector(orderFrontStandardAboutPanel:)
               keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Завершить" action:@selector(terminate:) keyEquivalent:@"q"];

    NSMenu *edit = [[NSMenu alloc] init];
    NSMenuItem *editItem = [[NSMenuItem alloc] init];
    [editItem setTitle:@"Правка"];
    [bar addItem:editItem];
    [editItem setSubmenu:edit];
    NSArray *rows = @[@[@"Отменить", @"undo:", @"z"],
                      @[@"Повторить", @"redo:", @"Z"],
                      @[@"", @"", @""],
                      @[@"Вырезать", @"cut:", @"x"],
                      @[@"Копировать", @"copy:", @"c"],
                      @[@"Вставить", @"paste:", @"v"],
                      @[@"Выбрать всё", @"selectAll:", @"a"]];
    for (NSArray *row in rows) {
        if ([row[0] length] == 0) {
            [edit addItem:[NSMenuItem separatorItem]];
        } else {
            [edit addItemWithTitle:row[0] action:NSSelectorFromString(row[1]) keyEquivalent:row[2]];
        }
    }

    NSMenu *view = [[NSMenu alloc] init];
    NSMenuItem *viewItem = [[NSMenuItem alloc] init];
    [viewItem setTitle:@"Вид"];
    [bar addItem:viewItem];
    [viewItem setSubmenu:view];
    [view addItemWithTitle:@"Обновить" action:@selector(reloadPage:) keyEquivalent:@"r"];
    [view addItem:[NSMenuItem separatorItem]];
    [view addItemWithTitle:@"Крупнее" action:@selector(zoomIn:) keyEquivalent:@"+"];
    [view addItemWithTitle:@"Мельче" action:@selector(zoomOut:) keyEquivalent:@"-"];
    [view addItemWithTitle:@"Обычный размер" action:@selector(zoomReset:) keyEquivalent:@"0"];

    NSMenu *win = [[NSMenu alloc] init];
    NSMenuItem *winItem = [[NSMenuItem alloc] init];
    [winItem setTitle:@"Окно"];
    [bar addItem:winItem];
    [winItem setSubmenu:win];
    [win addItemWithTitle:@"Свернуть" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
    [win addItemWithTitle:@"Вписать окно" action:@selector(performZoom:) keyEquivalent:@""];
    [win addItem:[NSMenuItem separatorItem]];
    [win addItemWithTitle:@"Собрать все окна" action:@selector(arrangeInFront:) keyEquivalent:@""];
}

- (NSRect)restoredFrame {
    NSString *saved = [[NSUserDefaults standardUserDefaults] stringForKey:kFrameKey];
    NSScreen *screen = [NSScreen mainScreen];
    NSRect visible = screen ? screen.frame : NSMakeRect(0, 0, 1440, 900);
    if (saved.length) {
        NSRect rect = NSRectFromString(saved);
        if (rect.size.width >= 900 && rect.size.height >= 600) return rect;
    }
    return NSMakeRect(60, 60, MIN(1440, visible.size.width - 80), MIN(900, visible.size.height - 80));
}

- (void)buildWindow {
    NSUInteger style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                       NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable;
    self.window = [[NSWindow alloc] initWithContentRect:[self restoredFrame]
                                              styleMask:style
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
    [self.window setTitle:@"ComfyUI MixMedia"];
    [self.window setMinSize:NSMakeSize(900, 600)];
    [self.window setReleasedWhenClosed:NO];
    [self.window setDelegate:self];

    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    self.web = [[WKWebView alloc] initWithFrame:[self.window contentLayoutRect] configuration:config];
    [self.web setAutoresizingMask:NSViewWidthSizable | NSViewHeightSizable];
    [self.web setNavigationDelegate:self];
    [self.web setUIDelegate:self];
    [self.window setContentView:self.web];

    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];

    [self.web loadHTMLString:WaitingPage() baseURL:nil];
    [self waitForServer];
}

- (void)waitForServer {
    NSURL *url = [NSURL URLWithString:[self.url stringByAppendingString:@"/"]];
    NSURLSessionDataTask *task = [[NSURLSession sharedSession]
        dataTaskWithURL:url
      completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            NSInteger code = [response isKindOfClass:[NSHTTPURLResponse class]]
                                 ? [(NSHTTPURLResponse *)response statusCode] : 0;
            if (code == 200) {
                [self.web loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:self.url]]];
                self.loaded = YES;
            } else {
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
                               dispatch_get_main_queue(), ^{ [self waitForServer]; });
            }
        });
      }];
    [task resume];
}

#pragma mark - окно

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app {
    return YES;
}

- (void)windowWillClose:(NSNotification *)note {
    [[NSUserDefaults standardUserDefaults] setObject:NSStringFromRect(self.window.frame)
                                              forKey:kFrameKey];
    [[NSUserDefaults standardUserDefaults] synchronize];
    [NSApp terminate:nil];
}

- (void)windowDidResize:(NSNotification *)note {
    [self.web setFrame:[self.window contentLayoutRect]];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
    [self.window makeKeyAndOrderFront:nil];
    return YES;
}

#pragma mark - стартовый воркфлоу

// При старте открываем наш холст вместо пустого «Unsaved Workflow» и ставим вид,
// сохранённый в самом файле (extra.ds). Если воркфлоу уже активен, с диска его
// не перезагружаем — иначе пропали бы несохранённые правки; правим только камеру.
- (void)loadHomeWorkflow {
    if (self.homeLoaded || self.homeWorkflow.length == 0) return;
    self.homeLoaded = YES;

    NSString *name = [self.homeWorkflow stringByReplacingOccurrencesOfString:@"'" withString:@""];
    NSString *file = [NSString stringWithFormat:@"/api/userdata/workflows%%2F%@.json", name];

    NSString *js = [NSString stringWithFormat:
        @"(function(){"
         "if (window.__mmHome) return; window.__mmHome = 1;"
         "var FILE = '%@', NAME = '%@';"
         "var tries = 0;"
         "function fitAll(){"
         "  try{"
         "    var c = window.app.canvas, ds = c.ds, nodes = window.app.graph._nodes || [];"
         "    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;"
         "    for (var i = 0; i < nodes.length; i++){"
         "      var b = nodes[i].getBounding ? nodes[i].getBounding() : null;"
         "      if (!b || !isFinite(b[0]) || !isFinite(b[1])) continue;"
         "      if (b[0] < minX) minX = b[0]; if (b[1] < minY) minY = b[1];"
         "      if (b[0] + b[2] > maxX) maxX = b[0] + b[2];"
         "      if (b[1] + b[3] > maxY) maxY = b[1] + b[3];"
         "    }"
         "    if (!isFinite(minX) || !isFinite(maxX)) return;"
         "    ds.fitToBounds([minX - 40, minY - 40, (maxX - minX) + 80, (maxY - minY) + 80]);"
         "    c.setDirty(true, true);"
         "  } catch(e){}"
         "}"
         "function anyVisible(){"
         "  try{"
         "    var c = window.app.canvas, ds = c.ds, nodes = window.app.graph._nodes || [];"
         "    ds.computeVisibleArea(c.viewport);"
         "    var va = ds.visible_area;"
         "    for (var i = 0; i < nodes.length; i++){"
         "      var b = nodes[i].getBounding ? nodes[i].getBounding() : null;"
         "      if (!b) continue;"
         "      if (b[0] < va[0] + va[2] && b[0] + b[2] > va[0] &&"
         "          b[1] < va[1] + va[3] && b[1] + b[3] > va[1]) return true;"
         "    }"
         "  } catch(e){}"
         "  return false;"
         "}"
         "function applyView(wf){"
         "  try{"
         "    var c = window.app.canvas, ds = c.ds;"
         "    var saved = wf && wf.extra && wf.extra.ds;"
         "    if (saved && isFinite(saved.scale) && saved.scale > 0 && saved.offset &&"
         "        isFinite(saved.offset[0]) && isFinite(saved.offset[1])) {"
         "      ds.scale = saved.scale;"
         "      ds.offset = [saved.offset[0], saved.offset[1]];"
         "      c.setDirty(true, true);"
         "      if (!anyVisible()) fitAll();"
         "    } else {"
         "      fitAll();"
         "    }"
         "  } catch(e){}"
         "}"
         "function ensureView(){"
         "  if (anyVisible()) return;"
         "  fetch(FILE, {cache:'no-store'}).then(function(r){ return r.json(); })"
         "    .then(applyView).catch(function(){ fitAll(); });"
         "}"
         "function isOurs(){"
         "  try{"
         "    var em = window.app.extensionManager, wm = em && em.workflow;"
         "    var act = wm && wm.activeWorkflow;"
         "    var path = act && act.path ? String(act.path) : '';"
         "    return path.indexOf(NAME) !== -1;"
         "  } catch(e){ return false; }"
         "}"
         "function load(){"
         "  fetch(FILE, {cache:'no-store'})"
         "    .then(function(r){ if (!r.ok) throw 0; return r.json(); })"
         "    .then(function(wf){"
         "      if (!wf || !wf.nodes || !wf.nodes.length) return;"
         "      return window.app.loadGraphData(wf, true, true, NAME)"
         "        .then(function(){ setTimeout(function(){ applyView(wf); }, 400); });"
         "    })"
         "    .catch(function(){});"
         "}"
         "function start(){"
         "  if (isOurs()) { setTimeout(ensureView, 500); return; }"
         "  load();"
         "}"
         "function tick(){"
         "  tries++;"
         "  var app = window.app;"
         "  if (app && typeof app.loadGraphData === 'function' && app.graph && app.canvas"
         "      && app.canvas.ds && window.innerWidth > 600) { setTimeout(start, 500); return; }"
         "  if (tries < 240) setTimeout(tick, 250);"
         "}"
         "tick();"
         "})();", file, name];

    [self.web evaluateJavaScript:js completionHandler:^(id result, NSError *error) {
        if (error) NSLog(@"home workflow: %@", error.localizedDescription);
    }];
}

#pragma mark - навигация

- (void)webView:(WKWebView *)webview didFinishNavigation:(WKNavigation *)navigation {
    [self loadHomeWorkflow];
}

- (BOOL)isLocal:(NSURL *)url {
    NSString *host = url.host ?: @"";
    return [host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"];
}

- (BOOL)isInternal:(NSURL *)url {
    NSString *scheme = [url.scheme lowercaseString] ?: @"";
    if ([scheme isEqualToString:@"about"] || [scheme isEqualToString:@"data"] ||
        [scheme isEqualToString:@"blob"] || [scheme isEqualToString:@"file"]) {
        return YES;
    }
    return [self isLocal:url];
}

- (WKWebView *)webView:(WKWebView *)webview
    createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration
               forNavigationAction:(WKNavigationAction *)action
                    windowFeatures:(WKWindowFeatures *)features {
    NSURL *target = action.request.URL;
    if ([self isInternal:target]) {
        [webview loadRequest:action.request];
    } else if (target) {
        [[NSWorkspace sharedWorkspace] openURL:target];
    }
    return nil;
}

- (void)webView:(WKWebView *)webview
    decidePolicyForNavigationAction:(WKNavigationAction *)action
                    decisionHandler:(void (^)(WKNavigationActionPolicy))handler {
    NSURL *target = action.request.URL;
    if (target && ![self isInternal:target]) {
        [[NSWorkspace sharedWorkspace] openURL:target];
        handler(WKNavigationActionPolicyCancel);
        return;
    }
    handler(WKNavigationActionPolicyAllow);
}

- (void)webView:(WKWebView *)webview
    decidePolicyForNavigationResponse:(WKNavigationResponse *)response
                      decisionHandler:(void (^)(WKNavigationResponsePolicy))handler {
    handler(response.canShowMIMEType ? WKNavigationResponsePolicyAllow
                                     : WKNavigationResponsePolicyDownload);
}

#pragma mark - загрузки

- (void)webView:(WKWebView *)webview
    navigationAction:(WKNavigationAction *)action
    didBecomeDownload:(WKDownload *)download {
    download.delegate = self;
}

- (void)webView:(WKWebView *)webview
    navigationResponse:(WKNavigationResponse *)response
     didBecomeDownload:(WKDownload *)download {
    download.delegate = self;
}

- (void)download:(WKDownload *)download
    decideDestinationUsingResponse:(NSURLResponse *)response
                 suggestedFilename:(NSString *)suggestedFilename
                 completionHandler:(void (^)(NSURL *_Nullable))completionHandler {
    NSFileManager *fm = [NSFileManager defaultManager];
    NSURL *dir = [fm URLsForDirectory:NSDownloadsDirectory inDomains:NSUserDomainMask].firstObject;
    if (!dir) dir = [NSURL fileURLWithPath:NSHomeDirectory()];
    NSString *name = suggestedFilename.length ? suggestedFilename : @"download";
    NSURL *dst = [dir URLByAppendingPathComponent:name];
    NSString *base = [dst.lastPathComponent stringByDeletingPathExtension];
    NSString *ext = dst.pathExtension;
    for (int i = 2; i < 1000 && [fm fileExistsAtPath:dst.path]; i++) {
        NSString *next = ext.length ? [NSString stringWithFormat:@"%@ %d.%@", base, i, ext]
                                    : [NSString stringWithFormat:@"%@ %d", base, i];
        dst = [dir URLByAppendingPathComponent:next];
    }
    completionHandler(dst);
}

#pragma mark - диалоги внутри страницы

// Без этого метода любой <input type=file> (открыть воркфлоу, загрузить картинку,
// MixmediaPick) молча ничего не делает.
- (void)webView:(WKWebView *)webview
    runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters
              initiatedByFrame:(WKFrameInfo *)frame
             completionHandler:(void (^)(NSArray<NSURL *> *_Nullable))completionHandler {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = parameters.allowsDirectories;
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection;
    panel.resolvesAliases = YES;

    void (^finish)(NSModalResponse) = ^(NSModalResponse result) {
        completionHandler(result == NSModalResponseOK ? panel.URLs : nil);
    };
    if (self.window) {
        [panel beginSheetModalForWindow:self.window completionHandler:finish];
    } else {
        finish([panel runModal]);
    }
}

- (void)webView:(WKWebView *)webview
    runJavaScriptAlertPanelWithMessage:(NSString *)message
                      initiatedByFrame:(WKFrameInfo *)frame
                     completionHandler:(void (^)(void))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:message ?: @""];
    [alert addButtonWithTitle:@"OK"];
    [self presentAlert:alert completion:^(NSModalResponse response) {
        (void)response;
        completionHandler();
    }];
}

- (void)webView:(WKWebView *)webview
    runJavaScriptConfirmPanelWithMessage:(NSString *)message
                        initiatedByFrame:(WKFrameInfo *)frame
                       completionHandler:(void (^)(BOOL))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:message ?: @""];
    [alert addButtonWithTitle:@"OK"];
    [alert addButtonWithTitle:@"Отмена"];
    [self presentAlert:alert completion:^(NSModalResponse response) {
        completionHandler(response == NSAlertFirstButtonReturn);
    }];
}

- (void)webView:(WKWebView *)webview
    runJavaScriptTextInputPanelWithPrompt:(NSString *)prompt
                             defaultText:(NSString *)defaultText
                        initiatedByFrame:(WKFrameInfo *)frame
                       completionHandler:(void (^)(NSString *_Nullable))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:prompt ?: @""];
    [alert addButtonWithTitle:@"OK"];
    [alert addButtonWithTitle:@"Отмена"];
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 24)];
    [field setStringValue:defaultText ?: @""];
    [alert setAccessoryView:field];
    [self presentAlert:alert completion:^(NSModalResponse response) {
        completionHandler(response == NSAlertFirstButtonReturn ? [field stringValue] : nil);
    }];
}

- (void)presentAlert:(NSAlert *)alert completion:(void (^)(NSModalResponse))completion {
    if (self.window) {
        [alert beginSheetModalForWindow:self.window completionHandler:completion];
    } else {
        completion([alert runModal]);
    }
}

#pragma mark - меню

- (void)reloadPage:(id)sender { [self.web reload]; }
- (void)zoomIn:(id)sender { [self.web setPageZoom:MIN(self.web.pageZoom * 1.1, 3.0)]; }
- (void)zoomOut:(id)sender { [self.web setPageZoom:MAX(self.web.pageZoom / 1.1, 0.4)]; }
- (void)zoomReset:(id)sender { [self.web setPageZoom:1.0]; }

#pragma mark - самопроверка

static NSString *MeasureScript(void) {
    return @"JSON.stringify({inner:[window.innerWidth,window.innerHeight],"
            "canvas:window.app&&window.app.canvas?[window.app.canvas.canvas.width,"
            "window.app.canvas.canvas.height]:null,"
            "nodes:window.app&&window.app.graph?window.app.graph._nodes.length:null,"
            "workflow:window.app&&window.app.extensionManager&&window.app.extensionManager.workflow"
            "&&window.app.extensionManager.workflow.activeWorkflow"
            "?window.app.extensionManager.workflow.activeWorkflow.path:null})";
}

- (void)measure:(NSString *)tag {
    [self.web evaluateJavaScript:MeasureScript()
               completionHandler:^(id result, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            self.measure[tag] = @{ @"value": result ? [result description] : @"",
                                   @"error": error ? [error description] : [NSNull null] };
        });
    }];
}

- (void)resizeTo:(NSRect)rect {
    [self.window setFrame:rect display:YES];
}

- (void)startSelftest {
    [[NSFileManager defaultManager] createDirectoryAtPath:kSelftestDir
                              withIntermediateDirectories:YES
                                               attributes:nil
                                                    error:nil];
    dispatch_queue_t work = dispatch_queue_create("selftest", DISPATCH_QUEUE_SERIAL);
    dispatch_async(work, ^{
        for (int i = 0; i < 90 && !self.loaded; i++) [NSThread sleepForTimeInterval:1.0];
        dispatch_async(dispatch_get_main_queue(), ^{ [self measure:@"before"]; });
        [NSThread sleepForTimeInterval:1.0];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self resizeTo:NSMakeRect(80, 80, 1100, 720)];
        });
        [NSThread sleepForTimeInterval:2.5];
        dispatch_async(dispatch_get_main_queue(), ^{ [self measure:@"after_small"]; });
        [NSThread sleepForTimeInterval:1.0];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self resizeTo:NSMakeRect(80, 80, 1500, 950)];
        });
        [NSThread sleepForTimeInterval:2.5];
        dispatch_async(dispatch_get_main_queue(), ^{ [self measure:@"after_big"]; });
        [NSThread sleepForTimeInterval:1.0];
        dispatch_async(dispatch_get_main_queue(), ^{
            WKSnapshotConfiguration *config = [[WKSnapshotConfiguration alloc] init];
            [self.web takeSnapshotWithConfiguration:config
                                  completionHandler:^(NSImage *image, NSError *error) {
                if (image) {
                    NSBitmapImageRep *rep =
                        [NSBitmapImageRep imageRepWithData:[image TIFFRepresentation]];
                    NSData *png = [rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
                    [png writeToFile:[kSelftestDir stringByAppendingPathComponent:@"window.png"]
                          atomically:YES];
                }
                NSData *json = [NSJSONSerialization dataWithJSONObject:self.measure
                                                               options:NSJSONWritingPrettyPrinted
                                                                 error:nil];
                [json writeToFile:[kSelftestDir stringByAppendingPathComponent:@"result.json"]
                       atomically:YES];
                NSLog(@"selftest %@", [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding]);
                [NSApp terminate:nil];
            }];
        });
    });
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        AppDelegate *delegate = [[AppDelegate alloc] init];
        [app setDelegate:delegate];
        [app run];
    }
    return 0;
}
