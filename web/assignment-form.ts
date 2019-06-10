"use strict";

var form: HTMLFormElement;

function campaign_count(campaign: HTMLSelectElement) {
  const opts = campaign.selectedOptions;
  if (opts.length == 1) {
    const count = <number><any>opts[0].dataset.count;
    const num = <HTMLInputElement>document.forms[0]['number'];
    num.max = <string><any>Math.min(1000, count);
    num.min = <string><any>Math.min(300, count);
  }
}

function main() {
  form = <HTMLFormElement>document.forms.namedItem('form');
  campaign_count(form['campaign']);
}

function change_campaign(event: Event) {
  campaign_count(<HTMLSelectElement>event.target);
}
