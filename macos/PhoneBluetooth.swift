import Cocoa
import CoreBluetooth
import Darwin

final class Bridge: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    let service = CBUUID(string:"b8a20001-51e9-4a0b-8e27-047c45f78210")
    let rxID = CBUUID(string:"b8a20002-51e9-4a0b-8e27-047c45f78210")
    let txID = CBUUID(string:"b8a20003-51e9-4a0b-8e27-047c45f78210")
    var central: CBCentralManager!
    var phone: CBPeripheral?
    var rx: CBCharacteristic?
    var tx: CBCharacteristic?
    let condition = NSCondition()
    var ready = false
    var failed = false
    var fd: Int32 = -1
    var lastActivity = Date()
    let wrote = DispatchSemaphore(value:0)
    let work = DispatchQueue(label:"phone.bluetooth.http")
    var listener: Int32 = -1
    override init() {
        super.init()
        listener = socket(AF_INET, SOCK_STREAM, 0)
        var reuse: Int32 = 1
        setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in(); address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET); address.sin_port = UInt16(8782).bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to:&address) { p in p.withMemoryRebound(to:sockaddr.self,capacity:1) { Darwin.bind(listener,$0,socklen_t(MemoryLayout<sockaddr_in>.size)) } }
        guard bound == 0, listen(listener,4) == 0 else { exit(0) }
        central = CBCentralManager(delegate:self,queue:nil)
        DispatchQueue.global(qos:.utility).async {
            while true { let client = accept(self.listener,nil,nil); if client >= 0 { self.work.async { self.serve(client) } } }
        }
        Timer.scheduledTimer(withTimeInterval:3,repeats:true) { _ in
            self.condition.lock(); let stalled = self.fd >= 0 && Date().timeIntervalSince(self.lastActivity)>40; self.condition.unlock()
            if stalled { self.disconnect() }
        }
    }
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state != .poweredOn { disconnect() }
    }
    func disconnect() {
        if let p = phone { central.cancelPeripheralConnection(p) }
        condition.lock(); ready=false; failed=true
        if fd >= 0 { shutdown(fd,SHUT_RDWR);fd = -1 }; condition.broadcast(); condition.unlock(); wrote.signal()
        phone=nil; rx=nil; tx=nil
    }
    func connect() -> Bool {
        condition.lock()
        if ready { condition.unlock(); return true }
        failed=false; condition.unlock()
        DispatchQueue.main.async {
            guard self.central.state == .poweredOn else { self.condition.lock();self.failed=true;self.condition.broadcast();self.condition.unlock();return }
            self.central.scanForPeripherals(withServices:[self.service],options:nil)
        }
        condition.lock(); let until=Date().addingTimeInterval(18)
        while !ready && !failed { if !condition.wait(until:until) { break } }
        let ok=ready; condition.unlock()
        DispatchQueue.main.async { self.central.stopScan(); if !ok { self.disconnect() } }
        return ok
    }
    func centralManager(_ central:CBCentralManager,didDiscover peripheral:CBPeripheral,advertisementData:[String:Any],rssi:NSNumber) {
        guard phone==nil else { return }; phone=peripheral; peripheral.delegate=self; central.stopScan();central.connect(peripheral,options:nil)
    }
    func centralManager(_ central:CBCentralManager,didConnect peripheral:CBPeripheral) { peripheral.discoverServices([service]) }
    func centralManager(_ central:CBCentralManager,didFailToConnect peripheral:CBPeripheral,error:Error?) { disconnect() }
    func centralManager(_ central:CBCentralManager,didDisconnectPeripheral peripheral:CBPeripheral,error:Error?) {
        condition.lock(); ready=false;failed=true;if fd>=0 { shutdown(fd,SHUT_RDWR);fd = -1 }; condition.broadcast();condition.unlock();wrote.signal();phone=nil;rx=nil;tx=nil
    }
    func peripheral(_ peripheral:CBPeripheral,didDiscoverServices error:Error?) {
        guard error==nil,let s=peripheral.services?.first(where:{$0.uuid==service}) else {disconnect();return}
        peripheral.discoverCharacteristics([rxID,txID],for:s)
    }
    func peripheral(_ peripheral:CBPeripheral,didDiscoverCharacteristicsFor service:CBService,error:Error?) {
        guard error==nil else {disconnect();return}
        rx=service.characteristics?.first(where:{$0.uuid==rxID});tx=service.characteristics?.first(where:{$0.uuid==txID})
        guard rx != nil,let output=tx else {disconnect();return};peripheral.setNotifyValue(true,for:output)
    }
    func peripheral(_ peripheral:CBPeripheral,didUpdateNotificationStateFor characteristic:CBCharacteristic,error:Error?) {
        guard error==nil,characteristic.isNotifying else {disconnect();return}
        condition.lock();ready=true;failed=false;condition.broadcast();condition.unlock()
    }
    func peripheral(_ peripheral:CBPeripheral,didWriteValueFor characteristic:CBCharacteristic,error:Error?) {
        if error != nil {disconnect()};wrote.signal()
    }
    func peripheral(_ peripheral:CBPeripheral,didUpdateValueFor characteristic:CBCharacteristic,error:Error?) {
        guard error==nil,let data=characteristic.value,let kind=data.first else {disconnect();return}
        condition.lock();lastActivity=Date();let dest=fd;condition.unlock();guard dest>=0 else {return}
        if kind==0 {
            let bytes=Data(data.dropFirst());if !sendAll(dest,bytes) {disconnect()}
        } else if kind==1 {
            condition.lock();fd = -1;condition.broadcast();condition.unlock();shutdown(dest,SHUT_WR)
        } else {disconnect()}
    }
    func sendAll(_ socket:Int32,_ data:Data)->Bool {
        return data.withUnsafeBytes { raw in
            guard let p=raw.baseAddress else {return true};var offset=0
            while offset<raw.count {let n=Darwin.send(socket,p.advanced(by:offset),raw.count-offset,0);if n<=0{return false};offset+=n};return true
        }
    }
    func write(_ data:Data)->Bool {
        while wrote.wait(timeout:.now()) == .success {}
        DispatchQueue.main.async { guard let p=self.phone,let c=self.rx else {self.wrote.signal();return};p.writeValue(data,for:c,type:.withResponse) }
        guard wrote.wait(timeout:.now()+15) == .success else {return false}
        condition.lock();let ok=ready && !failed;lastActivity=Date();condition.unlock();return ok
    }
    func serve(_ client:Int32) {
        defer {condition.lock();if fd==client {fd = -1};condition.unlock();Darwin.close(client)}
        var noSignal:Int32=1;setsockopt(client,SOL_SOCKET,SO_NOSIGPIPE,&noSignal,socklen_t(MemoryLayout<Int32>.size))
        var timeout=timeval(tv_sec:300,tv_usec:0);setsockopt(client,SOL_SOCKET,SO_RCVTIMEO,&timeout,socklen_t(MemoryLayout<timeval>.size));setsockopt(client,SOL_SOCKET,SO_SNDTIMEO,&timeout,socklen_t(MemoryLayout<timeval>.size))
        var request=Data();var buffer=[UInt8](repeating:0,count:4096);var expected:Int?
        while request.count<2*1024*1024+16384 {
            let n=recv(client,&buffer,buffer.count,0);if n<=0 {return};request.append(contentsOf:buffer.prefix(n))
            if expected==nil,let r=request.range(of:Data("\r\n\r\n".utf8)),let headers=String(data:request.prefix(r.lowerBound),encoding:.utf8) {
                var size=0;for line in headers.components(separatedBy:"\r\n") {if line.lowercased().hasPrefix("content-length:"){size=Int(line.dropFirst(15).trimmingCharacters(in:.whitespaces)) ?? -1}}
                guard size>=0 && size<=2*1024*1024 else {return};expected=r.upperBound+size
            }
            if let size=expected,request.count>=size {request=request.prefix(size);break}
        }
        guard expected != nil,connect() else { _=sendAll(client,Data("HTTP/1.1 503 Offline\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".utf8));return }
        condition.lock();fd=client;lastActivity=Date();condition.unlock()
        var maxChunk=19
        DispatchQueue.main.sync {maxChunk=max(19,(self.phone?.maximumWriteValueLength(for:.withResponse) ?? 20)-1)}
        var offset=0
        while offset<request.count {
            let end=min(request.count,offset+maxChunk);var packet=Data([0]);packet.append(request[offset..<end]);if !write(packet){DispatchQueue.main.async{self.disconnect()};return};offset=end
        }
        if !write(Data([1])){DispatchQueue.main.async{self.disconnect()};return}
        condition.lock()
        while fd>=0 && ready && !failed { _=condition.wait(until:Date().addingTimeInterval(3)) }
        if fd==client {fd = -1};condition.unlock()
    }
}
let app=NSApplication.shared;app.setActivationPolicy(.accessory)
let bridge=Bridge();app.run()
