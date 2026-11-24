package ru.ilya.lecturerecorder;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.*;
import android.os.*;
import org.json.*;
import java.io.*;
import java.net.Socket;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;

final class BleStream extends InputStream {
 static final UUID SERVICE=UUID.fromString("b8a10001-51e9-4a0b-8e27-047c45f78210"),CONTROL=UUID.fromString("b8a10002-51e9-4a0b-8e27-047c45f78210"),AUDIO=UUID.fromString("b8a10003-51e9-4a0b-8e27-047c45f78210"),CCC=UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
 static final UUID SECURE_CONTROL = UUID.fromString("b8a10005-51e9-4a0b-8e27-047c45f78210");
 private BluetoothGatt gatt;private BluetoothGattCharacteristic control;private BluetoothLeScanner scanner;private ScanCallback scan;private final Context context;private final String token;private final boolean bonded;private CountDownLatch ready=new CountDownLatch(1);private LinkedBlockingQueue<byte[]> packets=new LinkedBlockingQueue<>(256);private volatile String error="";private volatile boolean closed=false;private byte[] block=new byte[0],pending=null;private int cursor=0;private long expectedFrames=0,missing=0,expectedSequence=0;private JSONArray gaps=new JSONArray();
 static boolean hasTrustedDevice(Context context) {
  SharedPreferences settings = context.getSharedPreferences("settings", 0);
  String address = settings.getString("ble_address", "");
  if (!BluetoothAdapter.checkBluetoothAddress(address)) return false;
  if (Build.VERSION.SDK_INT >= 31 && context.checkSelfPermission("android.permission.BLUETOOTH_CONNECT") != 0) return false;
  try {
   BluetoothManager manager = context.getSystemService(BluetoothManager.class);
   BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
   if (adapter == null || !adapter.isEnabled()) return false;
   if (EspDeviceConnection.BONDED.equals(settings.getString(EspDeviceConnection.PAIRING_MODE, ""))) {
    return adapter.getRemoteDevice(address).getBondState() == BluetoothDevice.BOND_BONDED;
   }
   return !settings.getString("token", "").isEmpty();
  } catch (RuntimeException unavailable) {
   return false;
  }
 }

 BleStream(Context context, BooleanSupplier cancelled) throws Exception {
  this(context, cancelled, SystemClock.elapsedRealtime() + 20000, false);
 }

 BleStream(Context context, BooleanSupplier cancelled, long deadline, boolean trustedOnly) throws Exception {
  this.context = context;
  SharedPreferences settings = context.getSharedPreferences("settings", 0);
  token = settings.getString("token", "");
  bonded = EspDeviceConnection.BONDED.equals(settings.getString(EspDeviceConnection.PAIRING_MODE, ""));
  BluetoothManager manager = context.getSystemService(BluetoothManager.class);
  BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
  if (adapter == null || !adapter.isEnabled()) throw new IOException("Включи Bluetooth на телефоне");
  String address = settings.getString("ble_address", "");
  if (trustedOnly && (!BluetoothAdapter.checkBluetoothAddress(address) || (!bonded && token.isEmpty()))) {
   throw new IOException("Сначала подключи диктофон");
  }
  try {
   if (!address.isEmpty()) {
    connect(adapter.getRemoteDevice(address));
   } else {
    scanner = adapter.getBluetoothLeScanner();
    scan = new ScanCallback() {
     public void onScanResult(int type, ScanResult result) {
      if (closed) return;
      scanner.stopScan(this);
      scan = null;
      connect(result.getDevice());
     }
     public void onScanFailed(int code) { fail("Не удалось найти диктофон по Bluetooth"); }
    };
    scanner.startScan(Collections.singletonList(new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE)).build()),
       new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scan);
   }
   while (ready.getCount() != 0 && !cancelled.getAsBoolean()) {
    long remaining = deadline - SystemClock.elapsedRealtime();
    if (remaining <= 0) break;
    ready.await(Math.min(remaining, 100), TimeUnit.MILLISECONDS);
   }
   if (cancelled.getAsBoolean() || ready.getCount() != 0 || !error.isEmpty()) {
    throw new IOException(error.isEmpty() ? "Диктофон не найден по Bluetooth" : error);
   }
  } catch (Exception failure) {
   close();
   throw failure;
  }
 }
 private byte[] command(String action) {
  return (bonded ? action : action + " " + token).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
 }
 private void fail(String s){error=s;ready.countDown();packets.offer(new byte[0]);}
 private volatile long firstAudioNanos;
 long firstAudioNanos() { return firstAudioNanos; }
 private synchronized void connect(BluetoothDevice device){if(closed||gatt!=null)return;if(bonded&&device.getBondState()!=BluetoothDevice.BOND_BONDED){fail("Подключи ESP заново");return;}gatt=device.connectGatt(context,false,new BluetoothGattCallback(){
  public void onConnectionStateChange(BluetoothGatt g,int status,int state){if(closed)return;if(state==BluetoothProfile.STATE_CONNECTED&&status==0){g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH);g.setPreferredPhy(BluetoothDevice.PHY_LE_2M_MASK,BluetoothDevice.PHY_LE_2M_MASK,BluetoothDevice.PHY_OPTION_NO_PREFERRED);if(!g.requestMtu(517))fail("Не удалось настроить Bluetooth");}else if(state==BluetoothProfile.STATE_DISCONNECTED)fail("Bluetooth: связь потеряна");}
  public void onMtuChanged(BluetoothGatt g,int mtu,int status){if(closed)return;if(status!=0||mtu<185){fail("Недостаточный размер Bluetooth-пакета");return;}g.discoverServices();}
  public void onServicesDiscovered(BluetoothGatt g,int status){if(closed)return;BluetoothGattService s=g.getService(SERVICE);if(status!=0||s==null){fail("Это устройство не поддерживает запись лекций");return;}control=s.getCharacteristic(bonded?SECURE_CONTROL:CONTROL);BluetoothGattCharacteristic audio=s.getCharacteristic(AUDIO);if(control==null||audio==null){fail("Не найдены настройки ESP");return;}g.setCharacteristicNotification(audio,true);BluetoothGattDescriptor d=audio.getDescriptor(CCC);if(d==null){fail("Нет потока ESP");return;}d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);if(!g.writeDescriptor(d))fail("Не удалось включить поток ESP");}
  public void onDescriptorWrite(BluetoothGatt g,BluetoothGattDescriptor d,int status){if(closed)return;if(status!=0){fail("Не удалось включить поток ESP");return;}control.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);control.setValue(command("START"));if(!g.writeCharacteristic(control))fail("Не удалось начать запись");}
  public void onCharacteristicWrite(BluetoothGatt g,BluetoothGattCharacteristic c,int status){if(closed)return;if(status!=0||!g.readCharacteristic(c))fail("ESP не ответила на запуск");}
  private void checked(byte[] v,int status){if(closed)return;if(status==0&&v!=null&&"READY 16000 PCM16".equals(new String(v,java.nio.charset.StandardCharsets.US_ASCII).trim())){context.getSharedPreferences("settings",0).edit().putString("ble_address",device.getAddress()).apply();ready.countDown();}else fail("ESP не разрешила запись. Проверь подключение устройства");}
  public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] v,int status){checked(v,status);}
  public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,int status){checked(c.getValue(),status);}
  private void packet(byte[] value) {
   if (closed || !error.isEmpty()) return;
   if (value == null || value.length < 10 || value.length % 2 != 0) { fail("Некорректный Bluetooth-блок"); return; }
   if (firstAudioNanos == 0) {
    long frames = u32(value, 4) + (value.length - 8) / 2;
    firstAudioNanos = System.nanoTime() - frames * 1_000_000_000L / 16000;
   }
   if (!packets.offer(value.clone())) fail("Телефон не успевает сохранять Bluetooth-поток");
  }
  public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] v){packet(v);}
  public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c){packet(c.getValue());}
 },BluetoothDevice.TRANSPORT_LE);}
 private long u32(byte[] b,int offset){return ((long)b[offset]&255)|(((long)b[offset+1]&255)<<8)|(((long)b[offset+2]&255)<<16)|(((long)b[offset+3]&255)<<24);}
 private byte[] wrap(byte[] pcm){byte[] b=new byte[pcm.length+6];b[0]='P';b[1]='C';b[2]='M';b[3]='1';b[4]=(byte)pcm.length;b[5]=(byte)(pcm.length>>8);System.arraycopy(pcm,0,b,6,pcm.length);return b;}
 void prime(long deadline) throws IOException {
  next(Math.max(0, deadline - SystemClock.elapsedRealtime()));
 }
 private void next(long waitMillis)throws IOException{
  if(closed||!error.isEmpty())throw new IOException(error.isEmpty()?"Bluetooth закрыт":error);
  if(missing>0){int n=(int)Math.min(missing,2048);missing-=n;block=wrap(new byte[n*2]);cursor=0;return;}
  byte[] v=pending;pending=null;
  if(v==null){try{v=packets.poll(waitMillis,TimeUnit.MILLISECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();throw new IOException(e);}if(v==null)throw new IOException("Нет звука ESP по Bluetooth");if(v.length<10||v.length%2!=0)throw new IOException("Некорректный Bluetooth-блок");long seq=u32(v,0),offset=u32(v,4);if(offset<expectedFrames||seq<expectedSequence||offset-expectedFrames>160000)throw new IOException("Последовательность Bluetooth-блоков нарушена");if(offset>expectedFrames){try{gaps.put(new JSONObject().put("start",expectedFrames/16000.0).put("seconds",(offset-expectedFrames)/16000.0));}catch(JSONException e){throw new IOException(e);}missing=offset-expectedFrames;pending=v;expectedFrames=offset;expectedSequence=seq;next(waitMillis);return;}}
  expectedFrames=u32(v,4)+(v.length-8)/2;expectedSequence=u32(v,0)+1;block=wrap(Arrays.copyOfRange(v,8,v.length));cursor=0;
 }
 JSONArray takeGaps(){JSONArray result=gaps;gaps=new JSONArray();return result;}
 @Override public int read()throws IOException{byte[] b=new byte[1];read(b,0,1);return b[0]&255;}
 @Override public int read(byte[] b,int offset,int count)throws IOException{if(count==0)return 0;if(cursor==block.length)next(5000);int n=Math.min(count,block.length-cursor);System.arraycopy(block,cursor,b,offset,n);cursor+=n;return n;}
 @Override public synchronized void close(){if(closed)return;closed=true;try{if(scanner!=null&&scan!=null)scanner.stopScan(scan);if(gatt!=null){if(control!=null){control.setValue(command("STOP"));gatt.writeCharacteristic(control);}gatt.disconnect();gatt.close();}}catch(Exception ignored){}packets.clear();packets.offer(new byte[0]);}
 Socket socket(){BleStream source=this;return new Socket(){public InputStream getInputStream(){return source;}public OutputStream getOutputStream(){return new OutputStream(){public void write(int b){source.close();}};}public synchronized void close(){source.close();}};}
}
