"use strict";
var form;
function campaign_count(campaign) {
    var opts = campaign.selectedOptions;
    if (opts.length == 1) {
        var count = opts[0].dataset.count;
        var num = document.forms[0]['number'];
        num.max = Math.min(1000, count);
        num.min = Math.min(300, count);
    }
}
function main() {
    form = document.forms.namedItem('form');
    campaign_count(form['campaign']);
}
function change_campaign(event) {
    campaign_count(event.target);
}
//# sourceMappingURL=assignment-form.js.map