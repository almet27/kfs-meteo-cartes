package fr.kfsmeteo.widget;
import android.app.job.*;
import android.appwidget.AppWidgetManager;
import android.content.*;
import org.json.*;
public class WeatherJob extends JobService{
 static final int ID=275801,ONCE=275802;
 final java.util.Set<Integer> stopped=java.util.concurrent.ConcurrentHashMap.newKeySet();
 static void schedule(Context c){
  if(AppWidgetManager.getInstance(c).getAppWidgetIds(new ComponentName(c,WeatherWidget.class)).length==0)return;
  JobScheduler s=c.getSystemService(JobScheduler.class);ComponentName target=new ComponentName(c,WeatherJob.class);
  if(s.getPendingJob(ID)==null)s.schedule(new JobInfo.Builder(ID,target).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(3600000).build());
  if(s.getPendingJob(ONCE)==null)s.schedule(new JobInfo.Builder(ONCE,target).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).build());
 }
 @Override public boolean onStartJob(JobParameters p){stopped.remove(p.getJobId());new Thread(()->{java.util.List<java.util.concurrent.CompletableFuture<Void>> tasks=new java.util.ArrayList<>();for(String code:Kfs.cities(this).keySet()){tasks.add(java.util.concurrent.CompletableFuture.runAsync(()->{try{JSONObject d=Kfs.get("/api/city-forecast?code="+code);if(!d.has("models")||!Kfs.fresh(d))throw new Exception();if(!stopped.contains(p.getJobId())&&Kfs.cities(this).containsKey(code))Kfs.prefs(this).edit().putString("forecast_"+code,d.toString()).putBoolean("offline_"+code,false).apply();}catch(Exception e){if(!stopped.contains(p.getJobId())&&Kfs.cities(this).containsKey(code))Kfs.prefs(this).edit().putBoolean("offline_"+code,true).apply();}}));}java.util.concurrent.CompletableFuture.allOf(tasks.toArray(new java.util.concurrent.CompletableFuture<?>[0])).join();if(!stopped.contains(p.getJobId())){WeatherWidget.renderAll(this);jobFinished(p,false);}}).start();return true;}
 @Override public boolean onStopJob(JobParameters p){stopped.add(p.getJobId());return true;}
}