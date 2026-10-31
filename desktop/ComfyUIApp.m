// Окно приложения ComfyUI MixMedia: WKWebView в своём NSWindow, без браузера.
//
// Собирается в make_installer.sh:
//   clang -fobjc-arc -framework Cocoa -framework WebKit -O2 desktop/ComfyUIApp.m -o ComfyUIApp
// Лаунчер передаёт адрес сервера и путь к иконке:
//   ComfyUIApp http://127.0.0.1:8188 /Applications/.../app.icns
//
// MIXMEDIA_SELFTEST=1 — самопроверка: окно, ресайз, снимок в /tmp/mixmedia-selftest.

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

static NSString *const kFrameKey = @"mixmediaWindowFrame";
static NSString *const kDefaultURL = @"http://127.0.0.1:8188";
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

@interface AppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *web;
@property(nonatomic, strong) NSString *url;
@property(nonatomic, strong) NSString *logPath;
@property(nonatomic, strong) NSMutableDictionary *measure;
@property(nonatomic, assign) BOOL loaded;
@property(nonatomic, assign) BOOL selftest;
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

#pragma mark - ссылки

- (BOOL)isLocal:(NSURL *)url {
    NSString *host = url.host ?: @"";
    return [host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"];
}

- (WKWebView *)webView:(WKWebView *)webview
    createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration
               forNavigationAction:(WKNavigationAction *)action
                    windowFeatures:(WKWindowFeatures *)features {
    NSURL *target = action.request.URL;
    if (target) [[NSWorkspace sharedWorkspace] openURL:target];
    return nil;
}

- (void)webView:(WKWebView *)webview
    decidePolicyForNavigationAction:(WKNavigationAction *)action
                    decisionHandler:(void (^)(WKNavigationActionPolicy))handler {
    NSURL *target = action.request.URL;
    NSString *scheme = [target.scheme lowercaseString] ?: @"";
    if (target && ([scheme isEqualToString:@"http"] || [scheme isEqualToString:@"https"]) &&
        ![self isLocal:target]) {
        [[NSWorkspace sharedWorkspace] openURL:target];
        handler(WKNavigationActionPolicyCancel);
        return;
    }
    handler(WKNavigationActionPolicyAllow);
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
            "nodes:window.app&&window.app.graph?window.app.graph._nodes.length:null})";
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
