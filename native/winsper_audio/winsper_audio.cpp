#define NOMINMAX
#include <windows.h>
#include <audioclient.h>
#include <endpointvolume.h>
#include <propkeydef.h>
#include <functiondiscoverykeys_devpkey.h>
#include <ksmedia.h>
#include <mmdeviceapi.h>
#include <mmreg.h>
#include <propvarutil.h>
#include <wrl/client.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cwctype>
#include <iterator>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>

using Microsoft::WRL::ComPtr;
using Clock = std::chrono::steady_clock;

namespace {

std::wstring lower(std::wstring value) {
    std::transform(value.begin(), value.end(), value.begin(), [](wchar_t ch) {
        return static_cast<wchar_t>(std::towlower(ch));
    });
    return value;
}

bool unsafe_input_name(const std::wstring& value) {
    const auto name = lower(value);
    if (name.rfind(L"headset (", 0) == 0) return true;
    const wchar_t* blocked[] = {
        L"airpods", L"bluetooth", L"hands-free", L"hands free",
        L"earbuds", L"ear buds", L"buds"
    };
    for (const auto* token : blocked) {
        if (name.find(token) != std::wstring::npos) return true;
    }
    return false;
}

std::wstring device_property(IMMDevice* device, const PROPERTYKEY& key) {
    ComPtr<IPropertyStore> store;
    if (!device || FAILED(device->OpenPropertyStore(STGM_READ, &store))) return L"";
    PROPVARIANT value;
    PropVariantInit(&value);
    std::wstring result;
    if (SUCCEEDED(store->GetValue(key, &value)) && value.vt == VT_LPWSTR) {
        result = value.pwszVal ? value.pwszVal : L"";
    }
    PropVariantClear(&value);
    return result;
}

std::wstring friendly_name(IMMDevice* device) {
    ComPtr<IPropertyStore> store;
    if (!device || FAILED(device->OpenPropertyStore(STGM_READ, &store))) return L"";
    PROPVARIANT value;
    PropVariantInit(&value);
    std::wstring result;
    if (SUCCEEDED(store->GetValue(PKEY_Device_FriendlyName, &value)) && value.vt == VT_LPWSTR) {
        result = value.pwszVal ? value.pwszVal : L"";
    }
    PropVariantClear(&value);
    return result;
}

bool bluetooth_input_device(IMMDevice* device) {
    if (!device) return false;
    const auto enumerator = lower(device_property(device, PKEY_Device_EnumeratorName));
    return enumerator.find(L"bthenum") != std::wstring::npos ||
           enumerator.find(L"bluetooth") != std::wstring::npos ||
           unsafe_input_name(friendly_name(device));
}

bool has_any_token(const std::wstring& value, const wchar_t* const* tokens, size_t count) {
    const auto normalized = lower(value);
    for (size_t index = 0; index < count; ++index) {
        if (normalized.find(tokens[index]) != std::wstring::npos) return true;
    }
    return false;
}

bool internal_capture_device(IMMDevice* device) {
    if (!device || bluetooth_input_device(device)) return false;
    const auto name = friendly_name(device);
    const wchar_t* blocked[] = {
        L"usb", L"headset", L"headphone", L"earbud", L"airpod", L"bluetooth",
        L"webcam", L"camera", L"dock", L"virtual"
    };
    if (has_any_token(name, blocked, std::size(blocked))) return false;
    const wchar_t* internal[] = {
        L"realtek", L"microphone array", L"internal", L"built-in", L"built in",
        L"smart sound", L"cirrus"
    };
    return has_any_token(name, internal, std::size(internal));
}

bool internal_render_device(IMMDevice* device) {
    if (!device || bluetooth_input_device(device)) return false;
    const auto name = friendly_name(device);
    const wchar_t* blocked[] = {
        L"usb", L"hdmi", L"display", L"monitor", L"headset", L"headphone",
        L"earbud", L"airpod", L"bluetooth", L"digital audio", L"spdif",
        L"dock", L"virtual", L"nvidia", L"amd high definition"
    };
    if (has_any_token(name, blocked, std::size(blocked))) return false;
    const wchar_t* internal[] = {
        L"realtek", L"speaker", L"internal", L"built-in", L"built in", L"cirrus"
    };
    return has_any_token(name, internal, std::size(internal));
}

bool device_container_id(IMMDevice* device, GUID* output) {
    if (!device || !output) return false;
    ComPtr<IPropertyStore> store;
    if (FAILED(device->OpenPropertyStore(STGM_READ, &store))) return false;
    PROPVARIANT value;
    PropVariantInit(&value);
    const HRESULT hr = store->GetValue(PKEY_Device_ContainerId, &value);
    const bool valid = SUCCEEDED(hr) && value.vt == VT_CLSID && value.puuid;
    if (valid) *output = *value.puuid;
    PropVariantClear(&value);
    return valid;
}

bool same_internal_codec_family(IMMDevice* capture, IMMDevice* render) {
    const auto capture_name = lower(friendly_name(capture));
    const auto render_name = lower(friendly_name(render));
    const wchar_t* families[] = {L"realtek", L"cirrus", L"conexant"};
    for (const auto* family : families) {
        if (capture_name.find(family) != std::wstring::npos &&
            render_name.find(family) != std::wstring::npos) {
            return true;
        }
    }
    return false;
}


std::wstring endpoint_id(IMMDevice* device) {
    if (!device) return L"";
    LPWSTR value = nullptr;
    if (FAILED(device->GetId(&value)) || !value) return L"";
    std::wstring result(value);
    CoTaskMemFree(value);
    return result;
}

void copy_text(const std::wstring& value, wchar_t* output, int capacity) {
    if (!output || capacity <= 0) return;
    wcsncpy_s(output, static_cast<size_t>(capacity), value.c_str(), _TRUNCATE);
}

std::wstring hresult_text(const wchar_t* prefix, HRESULT value) {
    wchar_t code[32]{};
    swprintf_s(code, L"0x%08X", static_cast<unsigned int>(value));
    return std::wstring(prefix) + L" (" + code + L")";
}

class EndpointNotification final : public IMMNotificationClient {
public:
    EndpointNotification(
        HANDLE route_changed,
        IMMDeviceEnumerator* enumerator,
        std::wstring active_capture_id)
        : route_changed_(route_changed), enumerator_(enumerator) {
        if (!active_capture_id.empty()) supported_capture_ids_.insert(std::move(active_capture_id));
    }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(IMMNotificationClient)) {
            *object = static_cast<IMMNotificationClient*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&references_));
    }

    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (remaining == 0) delete this;
        return remaining;
    }

    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR device_id, DWORD) override {
        if (is_supported_capture_endpoint(device_id)) notify();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR device_id) override {
        if (is_supported_capture_endpoint(device_id)) notify();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR device_id) override {
        if (was_supported_capture_endpoint(device_id)) notify();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole, LPCWSTR device_id) override {
        if ((flow == eCapture || flow == eAll) && is_supported_capture_endpoint(device_id)) notify();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override {
        return S_OK;
    }

private:
    bool is_supported_capture_endpoint(LPCWSTR device_id) {
        if (!device_id || !*device_id || !enumerator_) return false;
        {
            std::lock_guard<std::mutex> guard(capture_ids_lock_);
            if (supported_capture_ids_.count(device_id)) return true;
        }
        ComPtr<IMMDevice> device;
        if (FAILED(enumerator_->GetDevice(device_id, &device)) || !device) return false;
        ComPtr<IMMEndpoint> endpoint;
        if (FAILED(device.As(&endpoint)) || !endpoint) return false;
        EDataFlow flow = eAll;
        if (FAILED(endpoint->GetDataFlow(&flow)) ||
            flow != eCapture || bluetooth_input_device(device.Get())) {
            return false;
        }
        std::lock_guard<std::mutex> guard(capture_ids_lock_);
        supported_capture_ids_.insert(device_id);
        return true;
    }

    bool was_supported_capture_endpoint(LPCWSTR device_id) {
        if (!device_id || !*device_id) return false;
        std::lock_guard<std::mutex> guard(capture_ids_lock_);
        return supported_capture_ids_.erase(device_id) > 0;
    }

    void notify() const {
        if (route_changed_) SetEvent(route_changed_);
    }

    ~EndpointNotification() = default;

    LONG references_ = 1;
    HANDLE route_changed_ = nullptr;
    ComPtr<IMMDeviceEnumerator> enumerator_;
    std::mutex capture_ids_lock_;
    std::unordered_set<std::wstring> supported_capture_ids_;
};

class Recorder {
public:
    explicit Recorder(std::wstring preferred)
        : preferred_(std::move(preferred)),
          shutdown_(CreateEventW(nullptr, TRUE, FALSE, nullptr)),
          command_(CreateEventW(nullptr, FALSE, FALSE, nullptr)),
          command_done_(CreateEventW(nullptr, FALSE, FALSE, nullptr)),
          packet_(CreateEventW(nullptr, FALSE, FALSE, nullptr)),
          route_changed_(CreateEventW(nullptr, FALSE, FALSE, nullptr)),
          graph_packet_(CreateEventW(nullptr, FALSE, FALSE, nullptr)),
          first_frame_(CreateEventW(nullptr, TRUE, FALSE, nullptr)),
          ready_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {
        worker_ = std::thread([this] { run(); });
        if (WaitForSingleObject(ready_, 5000) != WAIT_OBJECT_0) {
            set_error(L"Native microphone service did not initialize.");
        }
    }

    ~Recorder() {
        if (shutdown_) SetEvent(shutdown_);
        if (worker_.joinable()) worker_.join();
        for (HANDLE handle : {
                 shutdown_, command_, command_done_, packet_, route_changed_,
                 graph_packet_, first_frame_, ready_}) {
            if (handle) CloseHandle(handle);
        }
    }

    bool ready() const { return initialized_.load(); }

    bool start() { return issue(Command::Start); }
    bool stop() { return issue(Command::Stop); }

    bool wait_first_frame(DWORD timeout_ms) const {
        return WaitForSingleObject(first_frame_, timeout_ms) == WAIT_OBJECT_0;
    }

    double first_frame_ms() const { return first_frame_ms_.load(); }
    int sample_rate() const { return sample_rate_.load(); }
    int channels() const { return channels_.load(); }
    bool recording() const { return recording_.load(); }
    bool using_fallback() const { return using_fallback_.load(); }

    size_t sample_count() const {
        std::lock_guard<std::mutex> guard(samples_lock_);
        return samples_.size();
    }

    size_t copy_samples(float* output, size_t capacity) const {
        if (!output || capacity == 0) return 0;
        std::lock_guard<std::mutex> guard(samples_lock_);
        const size_t count = std::min(capacity, samples_.size());
        std::copy_n(samples_.data(), count, output);
        return count;
    }

    float peak() const { return peak_.load(); }

    std::wstring device_name() const {
        std::lock_guard<std::mutex> guard(state_lock_);
        return device_name_;
    }

    std::wstring error() const {
        std::lock_guard<std::mutex> guard(state_lock_);
        return last_error_;
    }

private:
    enum class Command { None, Start, Stop };

    bool issue(Command command) {
        std::lock_guard<std::mutex> guard(command_lock_);
        if (!initialized_.load()) return false;
        requested_.store(command);
        ResetEvent(command_done_);
        SetEvent(command_);
        if (WaitForSingleObject(command_done_, 4000) != WAIT_OBJECT_0) {
            set_error(L"Native microphone command timed out.");
            return false;
        }
        return command_ok_.load();
    }

    void set_error(const std::wstring& value) {
        std::lock_guard<std::mutex> guard(state_lock_);
        last_error_ = value;
    }

    std::wstring requested_name() const {
        std::wstring requested = preferred_;
        const auto suffix = lower(L", Windows WASAPI");
        auto requested_lower = lower(requested);
        if (requested_lower.size() >= suffix.size() &&
            requested_lower.compare(requested_lower.size() - suffix.size(), suffix.size(), suffix) == 0) {
            requested.resize(requested.size() - suffix.size());
        }
        return lower(requested);
    }

    ComPtr<IMMDevice> choose_device(
        IMMDeviceEnumerator* enumerator,
        bool* using_fallback = nullptr) {
        const auto requested_lower = requested_name();
        if (using_fallback) *using_fallback = false;

        ComPtr<IMMDeviceCollection> collection;
        if (FAILED(enumerator->EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE, &collection))) return nullptr;
        UINT count = 0;
        collection->GetCount(&count);
        ComPtr<IMMDevice> first_active;
        ComPtr<IMMDevice> internal_active;
        for (UINT index = 0; index < count; ++index) {
            ComPtr<IMMDevice> device;
            if (FAILED(collection->Item(index, &device))) continue;
            const auto name = friendly_name(device.Get());
            if (name.empty() || bluetooth_input_device(device.Get())) continue;
            if (!first_active) first_active = device;
            const auto normalized = lower(name);
            if (!internal_active &&
                (normalized.find(L"realtek") != std::wstring::npos ||
                 normalized.find(L"microphone array") != std::wstring::npos ||
                 normalized.find(L"internal") != std::wstring::npos)) {
                internal_active = device;
            }
            if (!requested_lower.empty() &&
                (normalized == requested_lower || normalized.find(requested_lower) != std::wstring::npos ||
                 requested_lower.find(normalized) != std::wstring::npos)) {
                return device;
            }
        }

        if (using_fallback) *using_fallback = !requested_lower.empty();
        ComPtr<IMMDevice> default_device;
        if (SUCCEEDED(enumerator->GetDefaultAudioEndpoint(eCapture, eConsole, &default_device)) &&
            !bluetooth_input_device(default_device.Get())) {
            return default_device;
        }
        if (internal_active) return internal_active;
        return first_active;
    }

    bool refresh_route_if_needed(bool force = false) {
        const bool route_ready = device_ && client_ && capture_;
        // Endpoint notifications refresh healthy routes while Winsper is idle.
        // Keep capture startup on the warmed fast path; only an unavailable
        // explicit route needs a bounded start-time retry.
        if (!force && route_ready && !using_fallback_.load()) return true;

        ComPtr<IMMDeviceEnumerator> enumerator;
        HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                      IID_PPV_ARGS(&enumerator));
        if (FAILED(hr)) {
            if (!route_ready) {
                set_error(hresult_text(L"Could not enumerate Windows microphones", hr));
            }
            return route_ready;
        }
        bool next_uses_fallback = false;
        ComPtr<IMMDevice> next = choose_device(enumerator.Get(), &next_uses_fallback);
        if (!next) {
            if (force || !route_ready) {
                release_audio();
                set_error(L"No supported Windows microphone is available. Use a built-in, wired, or USB microphone.");
                return false;
            }
            return true;
        }
        const auto current_id = endpoint_id(device_.Get());
        const auto next_id = endpoint_id(next.Get());
        if (route_ready && !current_id.empty() && current_id == next_id) {
            using_fallback_.store(next_uses_fallback);
            return true;
        }

        release_audio();
        if (initialize_audio()) return true;
        release_audio();
        return false;
    }

    bool initialize_audio() {
        ComPtr<IMMDeviceEnumerator> enumerator;
        HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                      IID_PPV_ARGS(&enumerator));
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not enumerate Windows microphones", hr));
            return false;
        }
        bool using_fallback = false;
        device_ = choose_device(enumerator.Get(), &using_fallback);
        if (!device_) {
            set_error(L"No supported Windows microphone is available. Use a built-in, wired, or USB microphone.");
            return false;
        }
        using_fallback_.store(using_fallback);
        {
            std::lock_guard<std::mutex> guard(state_lock_);
            device_name_ = friendly_name(device_.Get());
        }

        hr = device_->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, &client_);
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not activate Windows microphone", hr));
            return false;
        }
        AudioClientProperties properties{};
        properties.cbSize = sizeof(properties);
        properties.eCategory = AudioCategory_Media;
        properties.Options = AUDCLNT_STREAMOPTIONS_NONE;
        ComPtr<IAudioClient2> client2;
        if (SUCCEEDED(client_.As(&client2))) {
            // Media keeps capture on the selected endpoint without communications-mode routing.
            // The selected endpoint remains in shared mode.
            client2->SetClientProperties(&properties);
        }

        hr = client_->GetMixFormat(&format_);
        if (FAILED(hr) || !format_) {
            set_error(hresult_text(L"Could not read microphone format", hr));
            return false;
        }
        sample_rate_.store(static_cast<int>(format_->nSamplesPerSec));
        channels_.store(static_cast<int>(format_->nChannels));

        ComPtr<IAudioClient3> client3;
        if (SUCCEEDED(client_.As(&client3))) {
            UINT32 default_period = 0, fundamental = 0, minimum = 0, maximum = 0;
            hr = client3->GetSharedModeEnginePeriod(
                format_, &default_period, &fundamental, &minimum, &maximum);
            if (SUCCEEDED(hr)) {
                hr = client3->InitializeSharedAudioStream(
                    AUDCLNT_STREAMFLAGS_EVENTCALLBACK, default_period, format_, nullptr);
            }
        } else {
            hr = E_NOINTERFACE;
        }
        if (FAILED(hr)) {
            hr = client_->Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                1000000,
                0,
                format_,
                nullptr);
        }
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not initialize Windows microphone", hr));
            return false;
        }
        hr = client_->SetEventHandle(packet_);
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not attach microphone event", hr));
            return false;
        }
        hr = client_->GetService(IID_PPV_ARGS(&capture_));
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not open microphone capture service", hr));
            return false;
        }
        // Keep only the matching built-in codec awake. This optional client never
        // follows the user's output, never targets Bluetooth/USB/HDMI, and never
        // carries PCM. Failure affects latency only; microphone capture remains valid.
        initialize_graph_warmer(enumerator.Get());
        return true;
    }

    bool initialize_graph_warmer(IMMDeviceEnumerator* enumerator) {
        disable_graph_warmer();
        if (!enumerator || !graph_packet_ || !internal_capture_device(device_.Get())) return false;

        GUID capture_container{};
        const bool capture_has_container = device_container_id(device_.Get(), &capture_container);

        ComPtr<IMMDeviceCollection> collection;
        if (FAILED(enumerator->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &collection)) ||
            !collection) {
            return false;
        }
        UINT count = 0;
        if (FAILED(collection->GetCount(&count))) return false;
        ComPtr<IMMDevice> render_device;
        for (UINT index = 0; index < count; ++index) {
            ComPtr<IMMDevice> candidate;
            if (FAILED(collection->Item(index, &candidate)) ||
                !internal_render_device(candidate.Get())) {
                continue;
            }
            GUID render_container{};
            const bool render_has_container =
                device_container_id(candidate.Get(), &render_container);
            const bool same_container = capture_has_container && render_has_container &&
                IsEqualGUID(capture_container, render_container);
            const bool safe_family_fallback = (!capture_has_container || !render_has_container) &&
                same_internal_codec_family(device_.Get(), candidate.Get());
            if (same_container || safe_family_fallback) {
                render_device = candidate;
                break;
            }
        }
        if (!render_device) return false;

        ComPtr<IAudioClient> render_client;
        HRESULT hr = render_device->Activate(
            __uuidof(IAudioClient), CLSCTX_ALL, nullptr, &render_client);
        if (FAILED(hr) || !render_client) return false;

        AudioClientProperties properties{};
        properties.cbSize = sizeof(properties);
        properties.eCategory = AudioCategory_Media;
        properties.Options = AUDCLNT_STREAMOPTIONS_NONE;
        ComPtr<IAudioClient2> render_client2;
        if (SUCCEEDED(render_client.As(&render_client2))) {
            render_client2->SetClientProperties(&properties);
        }

        WAVEFORMATEX* render_format = nullptr;
        hr = render_client->GetMixFormat(&render_format);
        if (FAILED(hr) || !render_format) return false;

        ComPtr<IAudioClient3> render_client3;
        if (SUCCEEDED(render_client.As(&render_client3))) {
            UINT32 default_period = 0, fundamental = 0, minimum = 0, maximum = 0;
            hr = render_client3->GetSharedModeEnginePeriod(
                render_format, &default_period, &fundamental, &minimum, &maximum);
            if (SUCCEEDED(hr)) {
                hr = render_client3->InitializeSharedAudioStream(
                    AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                    default_period,
                    render_format,
                    nullptr);
            }
        } else {
            hr = E_NOINTERFACE;
        }
        if (FAILED(hr)) {
            hr = render_client->Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                1000000,
                0,
                render_format,
                nullptr);
        }
        if (FAILED(hr) || FAILED(render_client->SetEventHandle(graph_packet_))) {
            CoTaskMemFree(render_format);
            return false;
        }

        ComPtr<IAudioRenderClient> render;
        UINT32 buffer_frames = 0;
        if (FAILED(render_client->GetService(IID_PPV_ARGS(&render))) || !render ||
            FAILED(render_client->GetBufferSize(&buffer_frames)) || buffer_frames == 0) {
            CoTaskMemFree(render_format);
            return false;
        }

        graph_device_ = render_device;
        graph_client_ = render_client;
        graph_render_ = render;
        graph_format_ = render_format;
        graph_buffer_frames_ = buffer_frames;
        if (!start_graph_warmer()) {
            disable_graph_warmer();
            return false;
        }
        return true;
    }

    bool start_graph_warmer() {
        if (!graph_client_ || !graph_render_ || graph_buffer_frames_ == 0) return false;
        while (WaitForSingleObject(graph_packet_, 0) == WAIT_OBJECT_0) {}
        BYTE* ignored = nullptr;
        HRESULT hr = graph_render_->GetBuffer(graph_buffer_frames_, &ignored);
        if (FAILED(hr)) return false;
        hr = graph_render_->ReleaseBuffer(
            graph_buffer_frames_, AUDCLNT_BUFFERFLAGS_SILENT);
        if (FAILED(hr)) return false;
        hr = graph_client_->Start();
        if (FAILED(hr)) return false;
        graph_running_ = true;
        if (WaitForSingleObject(graph_packet_, 50) == WAIT_OBJECT_0 &&
            !refill_graph_warmer()) {
            return false;
        }
        return true;
    }

    bool refill_graph_warmer() {
        if (!graph_running_ || !graph_client_ || !graph_render_) return false;
        UINT32 padding = 0;
        if (FAILED(graph_client_->GetCurrentPadding(&padding)) ||
            padding > graph_buffer_frames_) {
            return false;
        }
        const UINT32 available = graph_buffer_frames_ - padding;
        if (available == 0) return true;
        BYTE* ignored = nullptr;
        if (FAILED(graph_render_->GetBuffer(available, &ignored))) return false;
        return SUCCEEDED(graph_render_->ReleaseBuffer(
            available, AUDCLNT_BUFFERFLAGS_SILENT));
    }

    void disable_graph_warmer() {
        if (graph_running_ && graph_client_) graph_client_->Stop();
        graph_running_ = false;
        graph_render_.Reset();
        graph_client_.Reset();
        graph_device_.Reset();
        graph_buffer_frames_ = 0;
        if (graph_format_) {
            CoTaskMemFree(graph_format_);
            graph_format_ = nullptr;
        }
        if (graph_packet_) ResetEvent(graph_packet_);
    }


    void run() {
        const HRESULT com_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        const bool com_initialized = SUCCEEDED(com_result);
        initialized_.store(com_initialized && initialize_audio());
        SetEvent(ready_);
        if (!initialized_.load()) {
            if (com_initialized) CoUninitialize();
            return;
        }

        ComPtr<IMMDeviceEnumerator> notification_enumerator;
        ComPtr<EndpointNotification> endpoint_notification;
        bool notification_registered = false;
        if (SUCCEEDED(CoCreateInstance(
                __uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                IID_PPV_ARGS(&notification_enumerator)))) {
            endpoint_notification.Attach(new (std::nothrow) EndpointNotification(
                route_changed_, notification_enumerator.Get(), endpoint_id(device_.Get())));
            if (endpoint_notification && SUCCEEDED(
                    notification_enumerator->RegisterEndpointNotificationCallback(
                        endpoint_notification.Get()))) {
                notification_registered = true;
            }
        }

        HANDLE waits[] = {shutdown_, command_, packet_, route_changed_, graph_packet_};
        bool running = true;
        while (running) {
            const DWORD result = WaitForMultipleObjects(5, waits, FALSE, INFINITE);
            if (result == WAIT_OBJECT_0) {
                running = false;
            } else if (result == WAIT_OBJECT_0 + 1) {
                process_command();
            } else if (result == WAIT_OBJECT_0 + 2 && recording_.load()) {
                drain_packets();
            } else if (result == WAIT_OBJECT_0 + 3) {
                if (recording_.load()) {
                    route_refresh_pending_.store(true);
                } else {
                    refresh_route_if_needed(true);
                }
            } else if (result == WAIT_OBJECT_0 + 4 && !refill_graph_warmer()) {
                disable_graph_warmer();
            }
        }
        if (notification_registered) {
            notification_enumerator->UnregisterEndpointNotificationCallback(
                endpoint_notification.Get());
        }
        release_audio();
        CoUninitialize();
    }

    void release_audio() {
        if (recording_.load() && client_) client_->Stop();
        recording_.store(false);
        disable_graph_warmer();
        capture_.Reset();
        client_.Reset();
        device_.Reset();
        if (format_) {
            CoTaskMemFree(format_);
            format_ = nullptr;
        }
    }

    void process_command() {
        const Command current = requested_.exchange(Command::None);
        bool ok = false;
        if (current == Command::Start) {
            ok = start_capture();
        } else if (current == Command::Stop) {
            ok = stop_capture();
        }
        command_ok_.store(ok);
        SetEvent(command_done_);
    }

    bool start_capture() {
        if (recording_.load()) return true;
        // Follow Windows current default route, or reacquire a selected safe endpoint that reappeared.
        // A healthy route skips enumeration on the hotkey path.
        if (!refresh_route_if_needed()) return false;
        if (microphone_input_blocked()) return false;
        {
            std::lock_guard<std::mutex> guard(samples_lock_);
            samples_.clear();
        }
        peak_.store(0.0f);
        first_frame_ms_.store(0.0);
        ResetEvent(first_frame_);
        while (WaitForSingleObject(packet_, 0) == WAIT_OBJECT_0) {}
        const HRESULT reset = client_->Reset();
        if (FAILED(reset) && reset != AUDCLNT_E_NOT_STOPPED) {
            set_error(hresult_text(L"Could not reset Windows microphone", reset));
            return false;
        }
        started_at_ = Clock::now();
        const HRESULT hr = client_->Start();
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not start Windows microphone", hr));
            return false;
        }
        recording_.store(true);
        return true;
    }

    bool microphone_input_blocked() {
        if (!device_) return false;
        ComPtr<IAudioEndpointVolume> volume;
        HRESULT hr = device_->Activate(
            __uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr, &volume);
        if (FAILED(hr) || !volume) return false;

        BOOL muted = FALSE;
        if (SUCCEEDED(volume->GetMute(&muted)) && muted) {
            set_error(L"The selected microphone is muted in Windows. Unmute it and try again.");
            return true;
        }
        float level = 1.0f;
        if (SUCCEEDED(volume->GetMasterVolumeLevelScalar(&level)) && level <= 0.0001f) {
            set_error(L"The selected microphone input level is set to zero in Windows. Raise it and try again.");
            return true;
        }
        return false;
    }

    bool stop_capture() {
        if (!recording_.load()) {
            set_error(L"Recorder was not running.");
            return false;
        }
        drain_packets();
        const HRESULT hr = client_->Stop();
        drain_packets();
        recording_.store(false);
        if (route_refresh_pending_.exchange(false)) SetEvent(route_changed_);
        if (FAILED(hr)) {
            set_error(hresult_text(L"Could not stop Windows microphone", hr));
            return false;
        }
        return true;
    }

    bool is_float_format() const {
        if (format_->wFormatTag == WAVE_FORMAT_IEEE_FLOAT) return true;
        if (format_->wFormatTag != WAVE_FORMAT_EXTENSIBLE) return false;
        const auto* extensible = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(format_);
        return IsEqualGUID(extensible->SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
    }

    float sample_value(const BYTE* data, UINT32 frame, UINT16 channel) const {
        const UINT16 channel_count = std::max<UINT16>(1, format_->nChannels);
        const size_t index = static_cast<size_t>(frame) * channel_count + channel;
        if (is_float_format() && format_->wBitsPerSample == 32) {
            return reinterpret_cast<const float*>(data)[index];
        }
        if (format_->wBitsPerSample == 16) {
            return static_cast<float>(reinterpret_cast<const int16_t*>(data)[index]) / 32768.0f;
        }
        if (format_->wBitsPerSample == 32) {
            return static_cast<float>(reinterpret_cast<const int32_t*>(data)[index] / 2147483648.0);
        }
        if (format_->wBitsPerSample == 24) {
            const BYTE* value = data + index * 3;
            int32_t decoded = value[0] | (value[1] << 8) | (value[2] << 16);
            if (decoded & 0x800000) decoded |= ~0xFFFFFF;
            return static_cast<float>(decoded) / 8388608.0f;
        }
        return 0.0f;
    }

    void drain_packets() {
        if (!capture_) return;
        UINT32 packet_frames = 0;
        while (SUCCEEDED(capture_->GetNextPacketSize(&packet_frames)) && packet_frames > 0) {
            BYTE* data = nullptr;
            DWORD flags = 0;
            UINT64 device_position = 0;
            UINT64 qpc_position = 0;
            UINT32 frames = 0;
            const HRESULT hr = capture_->GetBuffer(
                &data, &frames, &flags, &device_position, &qpc_position);
            if (FAILED(hr)) {
                set_error(hresult_text(L"Could not read microphone packet", hr));
                return;
            }
            std::vector<float> packet_samples(frames, 0.0f);
            float packet_peak = 0.0f;
            if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT) && data) {
                const UINT16 channel_count = std::max<UINT16>(1, format_->nChannels);
                for (UINT32 frame = 0; frame < frames; ++frame) {
                    float value = 0.0f;
                    for (UINT16 channel = 0; channel < channel_count; ++channel) {
                        value += sample_value(data, frame, channel);
                    }
                    value /= static_cast<float>(channel_count);
                    packet_samples[frame] = value;
                    packet_peak = std::max(packet_peak, std::abs(value));
                }
            }
            capture_->ReleaseBuffer(frames);
            {
                std::lock_guard<std::mutex> guard(samples_lock_);
                samples_.insert(samples_.end(), packet_samples.begin(), packet_samples.end());
            }
            peak_.store(std::max(peak_.load(), packet_peak));
            if (WaitForSingleObject(first_frame_, 0) != WAIT_OBJECT_0) {
                const double latency = std::chrono::duration<double, std::milli>(
                    Clock::now() - started_at_).count();
                first_frame_ms_.store(latency);
                SetEvent(first_frame_);
            }
        }
    }

    std::wstring preferred_;
    HANDLE shutdown_ = nullptr;
    HANDLE command_ = nullptr;
    HANDLE command_done_ = nullptr;
    HANDLE packet_ = nullptr;
    HANDLE route_changed_ = nullptr;
    HANDLE graph_packet_ = nullptr;
    HANDLE first_frame_ = nullptr;
    HANDLE ready_ = nullptr;
    std::thread worker_;
    mutable std::mutex command_lock_;
    mutable std::mutex samples_lock_;
    mutable std::mutex state_lock_;
    std::atomic<Command> requested_{Command::None};
    std::atomic<bool> command_ok_{false};
    std::atomic<bool> initialized_{false};
    std::atomic<bool> recording_{false};
    std::atomic<bool> route_refresh_pending_{false};
    std::atomic<bool> using_fallback_{false};
    std::atomic<double> first_frame_ms_{0.0};
    std::atomic<int> sample_rate_{0};
    std::atomic<int> channels_{0};
    std::atomic<float> peak_{0.0f};
    std::vector<float> samples_;
    std::wstring device_name_;
    std::wstring last_error_;
    Clock::time_point started_at_{};
    ComPtr<IMMDevice> device_;
    ComPtr<IAudioClient> client_;
    ComPtr<IAudioCaptureClient> capture_;
    WAVEFORMATEX* format_ = nullptr;
    ComPtr<IMMDevice> graph_device_;
    ComPtr<IAudioClient> graph_client_;
    ComPtr<IAudioRenderClient> graph_render_;
    WAVEFORMATEX* graph_format_ = nullptr;
    UINT32 graph_buffer_frames_ = 0;
    std::atomic<bool> graph_running_{false};
};

}  // namespace

extern "C" {

__declspec(dllexport) void* __cdecl winsper_audio_create(
    const wchar_t* preferred, wchar_t* error, int error_capacity) {
    auto* recorder = new (std::nothrow) Recorder(preferred ? preferred : L"");
    if (!recorder || !recorder->ready()) {
        copy_text(recorder ? recorder->error() : L"Could not allocate microphone service.", error, error_capacity);
        delete recorder;
        return nullptr;
    }
    return recorder;
}

__declspec(dllexport) void __cdecl winsper_audio_destroy(void* value) {
    delete static_cast<Recorder*>(value);
}

__declspec(dllexport) int __cdecl winsper_audio_start(void* value) {
    return value && static_cast<Recorder*>(value)->start() ? 1 : 0;
}

__declspec(dllexport) int __cdecl winsper_audio_stop(void* value) {
    return value && static_cast<Recorder*>(value)->stop() ? 1 : 0;
}

__declspec(dllexport) int __cdecl winsper_audio_wait_first_frame(void* value, unsigned int timeout_ms) {
    return value && static_cast<Recorder*>(value)->wait_first_frame(timeout_ms) ? 1 : 0;
}

__declspec(dllexport) double __cdecl winsper_audio_first_frame_ms(void* value) {
    return value ? static_cast<Recorder*>(value)->first_frame_ms() : 0.0;
}

__declspec(dllexport) int __cdecl winsper_audio_sample_rate(void* value) {
    return value ? static_cast<Recorder*>(value)->sample_rate() : 0;
}

__declspec(dllexport) int __cdecl winsper_audio_channels(void* value) {
    return value ? static_cast<Recorder*>(value)->channels() : 0;
}

__declspec(dllexport) int __cdecl winsper_audio_using_fallback(void* value) {
    return value && static_cast<Recorder*>(value)->using_fallback() ? 1 : 0;
}

__declspec(dllexport) size_t __cdecl winsper_audio_sample_count(void* value) {
    return value ? static_cast<Recorder*>(value)->sample_count() : 0;
}

__declspec(dllexport) size_t __cdecl winsper_audio_copy_samples(
    void* value, float* output, size_t capacity) {
    return value ? static_cast<Recorder*>(value)->copy_samples(output, capacity) : 0;
}

__declspec(dllexport) float __cdecl winsper_audio_peak(void* value) {
    return value ? static_cast<Recorder*>(value)->peak() : 0.0f;
}

__declspec(dllexport) int __cdecl winsper_audio_is_recording(void* value) {
    return value && static_cast<Recorder*>(value)->recording() ? 1 : 0;
}

__declspec(dllexport) void __cdecl winsper_audio_device_name(
    void* value, wchar_t* output, int capacity) {
    copy_text(value ? static_cast<Recorder*>(value)->device_name() : L"", output, capacity);
}

__declspec(dllexport) void __cdecl winsper_audio_last_error(
    void* value, wchar_t* output, int capacity) {
    copy_text(value ? static_cast<Recorder*>(value)->error() : L"Native microphone service unavailable.",
              output, capacity);
}

}
