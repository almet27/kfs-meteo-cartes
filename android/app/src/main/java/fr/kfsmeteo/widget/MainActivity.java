package fr.kfsmeteo.widget;
import android.app.*;
import android.appwidget.AppWidgetManager;
import android.content.*;
import android.net.Uri;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import java.net.URLEncoder;
import java.util.ArrayList;
import org.json.*;
public class MainActivity extends Activity {
 LinearLayout selected; EditText query; TextView status; Spinner choices; Button save; final ArrayList<JSONObject> cities=new ArrayList<>(); int serial=0;
 @Override public void onCreate(Bundle b){super.onCreate(b);
  LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);int p=(int)(20*getResources().getDisplayMetrics().density);l.setPadding(p,p*2,p,p);l.setBackgroundColor(0xff10243a);
  ScrollView scroll=new ScrollView(this);scroll.addView(l);setContentView(scroll);
  TextView title=new TextView(this);title.setText("KFS MÉTÉO");title.setTextSize(28);l.addView(title);
  TextView intro=new TextView(this);intro.setText("Choisissez jusqu’à quatre communes pour les widgets de votre écran d’accueil. Les valeurs sont des prévisions, et non des mesures de station.");l.addView(intro);
  status=new TextView(this);status.setText("Vos communes");l.addView(status);selected=new LinearLayout(this);selected.setOrientation(LinearLayout.VERTICAL);l.addView(selected);showSelected();
  query=new EditText(this);query.setSingleLine();query.setHint("Commune ou code postal");l.addView(query);
  Button find=new Button(this);find.setText("Rechercher");l.addView(find);
  choices=new Spinner(this);l.addView(choices);
  save=new Button(this);save.setText("Ajouter la commune");save.setEnabled(false);l.addView(save);
  Button pin=new Button(this);pin.setText("Ajouter le widget à l’écran d’accueil");l.addView(pin);
  Button site=new Button(this);site.setText("Ouvrir KFS Météo");l.addView(site);
  find.setOnClickListener(v->search());
  save.setOnClickListener(v->{int i=choices.getSelectedItemPosition();if(i<0||i>=cities.size())return;JSONObject j=cities.get(i);String code=j.optString("code"),name=j.optString("name");if(!Kfs.valid(code))return;java.util.LinkedHashMap<String,String> list=Kfs.cities(this);if(list.containsKey(code)){status.setText("Commune déjà ajoutée.");return;}if(list.size()>=4){status.setText("Maximum 4 communes.");return;}list.put(code,name);Kfs.saveCities(this,list);showSelected();status.setText("Commune ajoutée.");WeatherWidget.renderAll(this);WeatherJob.schedule(this);});
  pin.setOnClickListener(v->{if(Kfs.cities(this).isEmpty()){status.setText("Enregistrez une commune d’abord.");return;}AppWidgetManager a=AppWidgetManager.getInstance(this);if(a.isRequestPinAppWidgetSupported())a.requestPinAppWidget(new ComponentName(this,WeatherWidget.class),null,null);else status.setText("Appui long sur l’écran d’accueil → Widgets → KFS Météo.");});
  site.setOnClickListener(v->startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(Kfs.BASE))));
 }
 void showSelected(){selected.removeAllViews();java.util.LinkedHashMap<String,String> list=Kfs.cities(this);for(java.util.Map.Entry<String,String> e:list.entrySet()){String code=e.getKey();LinearLayout row=new LinearLayout(this);row.setOrientation(LinearLayout.HORIZONTAL);TextView label=new TextView(this);label.setText(e.getValue());row.addView(label,new LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1));Button remove=new Button(this);remove.setText("Retirer");row.addView(remove);remove.setOnClickListener(v->{java.util.LinkedHashMap<String,String> current=Kfs.cities(this);current.remove(code);Kfs.saveCities(this,current);showSelected();WeatherWidget.renderAll(this);WeatherJob.schedule(this);});selected.addView(row);}}
 void search(){String q=query.getText().toString().trim();if(q.length()<2||q.length()>80){status.setText("Saisissez un nom ou un code postal.");return;}int n=++serial;save.setEnabled(false);status.setText("Recherche…");
  new Thread(()->{try{JSONArray a=Kfs.get("/api/city-search?q="+URLEncoder.encode(q,"UTF-8")).getJSONArray("cities");ArrayList<JSONObject> result=new ArrayList<>();ArrayList<String> labels=new ArrayList<>();for(int i=0;i<a.length();i++){JSONObject j=a.getJSONObject(i);if(Kfs.valid(j.optString("code"))){result.add(j);labels.add(j.optString("name")+" ("+j.optString("department")+")");}}runOnUiThread(()->{if(n!=serial||isFinishing())return;cities.clear();cities.addAll(result);ArrayAdapter<String> ad=new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,labels);choices.setAdapter(ad);save.setEnabled(!cities.isEmpty());status.setText(cities.isEmpty()?"Aucune commune trouvée.":"Sélectionnez votre commune.");});}catch(Exception e){runOnUiThread(()->{if(n==serial&&!isFinishing())status.setText("Recherche indisponible. Réessayez.");});}}).start();
 }
}