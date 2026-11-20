var Firework;
async function startup({id,rootURI}) {
  await Zotero.initializationPromise;
  Services.scriptloader.loadSubScript(rootURI+'firework.js');
  Firework=FireworkPlugin;
  await Firework.start(id,rootURI);
}
function shutdown(){Firework?.stop();Firework=undefined;}
function install(){}
function uninstall(){}
