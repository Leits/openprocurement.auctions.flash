# -*- coding: utf-8 -*-
from openprocurement.api.models import get_now
from openprocurement.api.utils import (
    context_unpack,
    json_view,
    set_ownership,
    APIResource,
)
from openprocurement.auctions.core.utils import (
    apply_patch,
    check_auction_status,
    opresource,
    save_auction,

)
from openprocurement.auctions.core.validation import (
    validate_complaint_data,
    validate_patch_complaint_data,
)


@opresource(name='Auction Award Complaints',
            collection_path='/auctions/{auction_id}/awards/{award_id}/complaints',
            path='/auctions/{auction_id}/awards/{award_id}/complaints/{complaint_id}',
            auctionsprocurementMethodType="belowThreshold",
            description="Auction award complaints")
class AuctionAwardComplaintResource(APIResource):

    @json_view(content_type="application/json", permission='create_award_complaint', validators=(validate_complaint_data,))
    def collection_post(self):
        """Post a complaint for award
        """
        auction = self.request.validated['auction']
        if auction.status not in ['active.qualification', 'active.awarded']:
            self.request.errors.add('body', 'data', 'Can\'t add complaint in current ({}) auction status'.format(auction.status))
            self.request.errors.status = 403
            return
        if any([i.status != 'active' for i in auction.lots if i.id == self.context.lotID]):
            self.request.errors.add('body', 'data', 'Can add complaint only in active lot status')
            self.request.errors.status = 403
            return
        if self.context.complaintPeriod and \
           (self.context.complaintPeriod.startDate and self.context.complaintPeriod.startDate > get_now() or
                self.context.complaintPeriod.endDate and self.context.complaintPeriod.endDate < get_now()):
            self.request.errors.add('body', 'data', 'Can add complaint only in complaintPeriod')
            self.request.errors.status = 403
            return
        complaint = self.request.validated['complaint']
        complaint.date = get_now()
        complaint.relatedLot = self.context.lotID
        if complaint.status == 'claim':
            complaint.dateSubmitted = get_now()
        else:
            complaint.status = 'draft'
        complaint.complaintID = '{}.{}{}'.format(auction.auctionID, self.server_id, sum([len(i.complaints) for i in auction.awards], len(auction.complaints)) + 1)
        set_ownership(complaint, self.request)
        self.context.complaints.append(complaint)
        if save_auction(self.request):
            self.LOGGER.info('Created auction award complaint {}'.format(complaint.id),
                        extra=context_unpack(self.request, {'MESSAGE_ID': 'auction_award_complaint_create'}, {'complaint_id': complaint.id}))
            self.request.response.status = 201
            self.request.response.headers['Location'] = self.request.route_url('Auction Award Complaints', auction_id=auction.id, award_id=self.request.validated['award_id'], complaint_id=complaint['id'])
            return {
                'data': complaint.serialize("view"),
                'access': {
                    'token': complaint.owner_token
                }
            }

    @json_view(permission='view_auction')
    def collection_get(self):
        """List complaints for award
        """
        return {'data': [i.serialize("view") for i in self.context.complaints]}

    @json_view(permission='view_auction')
    def get(self):
        """Retrieving the complaint for award
        """
        return {'data': self.context.serialize("view")}

    @json_view(content_type="application/json", permission='edit_complaint', validators=(validate_patch_complaint_data,))
    def patch(self):
        """Post a complaint resolution for award
        """
        auction = self.request.validated['auction']
        if auction.status not in ['active.qualification', 'active.awarded']:
            self.request.errors.add('body', 'data', 'Can\'t update complaint in current ({}) auction status'.format(auction.status))
            self.request.errors.status = 403
            return
        if any([i.status != 'active' for i in auction.lots if i.id == self.request.validated['award'].lotID]):
            self.request.errors.add('body', 'data', 'Can update complaint only in active lot status')
            self.request.errors.status = 403
            return
        if self.context.status not in ['draft', 'claim', 'answered', 'pending']:
            self.request.errors.add('body', 'data', 'Can\'t update complaint in current ({}) status'.format(self.context.status))
            self.request.errors.status = 403
            return
        data = self.request.validated['data']
        complaintPeriod = self.request.validated['award'].complaintPeriod
        is_complaintPeriod = complaintPeriod.startDate < get_now() and complaintPeriod.endDate > get_now() if complaintPeriod.endDate else complaintPeriod.startDate < get_now()
        # complaint_owner
        if self.request.authenticated_role == 'complaint_owner' and self.context.status in ['draft', 'claim', 'answered', 'pending'] and data.get('status', self.context.status) == 'cancelled':
            apply_patch(self.request, save=False, src=self.context.serialize())
            self.context.dateCanceled = get_now()
        elif self.request.authenticated_role == 'complaint_owner' and is_complaintPeriod and self.context.status == 'draft' and data.get('status', self.context.status) == self.context.status:
            apply_patch(self.request, save=False, src=self.context.serialize())
        elif self.request.authenticated_role == 'complaint_owner' and is_complaintPeriod and self.context.status == 'draft' and data.get('status', self.context.status) == 'claim':
            apply_patch(self.request, save=False, src=self.context.serialize())
            self.context.dateSubmitted = get_now()
        elif self.request.authenticated_role == 'complaint_owner' and self.context.status == 'answered' and data.get('status', self.context.status) == self.context.status:
            apply_patch(self.request, save=False, src=self.context.serialize())
        elif self.request.authenticated_role == 'complaint_owner' and self.context.status == 'answered' and data.get('satisfied', self.context.satisfied) is True and data.get('status', self.context.status) == 'resolved':
            apply_patch(self.request, save=False, src=self.context.serialize())
        elif self.request.authenticated_role == 'complaint_owner' and self.context.status == 'answered' and data.get('satisfied', self.context.satisfied) is False and data.get('status', self.context.status) == 'pending':
            apply_patch(self.request, save=False, src=self.context.serialize())
            self.context.type = 'complaint'
            self.context.dateEscalated = get_now()
        # auction_owner
        elif self.request.authenticated_role == 'auction_owner' and self.context.status == 'claim' and data.get('status', self.context.status) == self.context.status:
            apply_patch(self.request, save=False, src=self.context.serialize())
        elif self.request.authenticated_role == 'auction_owner' and self.context.status == 'claim' and data.get('resolution', self.context.resolution) and len(data.get('resolution', self.context.resolution or "")) >= 20 and data.get('resolutionType', self.context.resolutionType) and data.get('status', self.context.status) == 'answered':
            apply_patch(self.request, save=False, src=self.context.serialize())
            self.context.dateAnswered = get_now()
        elif self.request.authenticated_role == 'auction_owner' and self.context.status == 'pending':
            apply_patch(self.request, save=False, src=self.context.serialize())
        # reviewers
        elif self.request.authenticated_role == 'reviewers' and self.context.status == 'pending' and data.get('status', self.context.status) == self.context.status:
            apply_patch(self.request, save=False, src=self.context.serialize())
        elif self.request.authenticated_role == 'reviewers' and self.context.status == 'pending' and data.get('status', self.context.status) in ['resolved', 'invalid', 'declined']:
            apply_patch(self.request, save=False, src=self.context.serialize())
            self.context.dateDecision = get_now()
        else:
            self.request.errors.add('body', 'data', 'Can\'t update complaint')
            self.request.errors.status = 403
            return
        if self.context.tendererAction and not self.context.tendererActionDate:
            self.context.tendererActionDate = get_now()
        if self.context.status not in ['draft', 'claim', 'answered', 'pending'] and auction.status in ['active.qualification', 'active.awarded']:
            check_auction_status(self.request)
        if save_auction(self.request):
            self.LOGGER.info('Updated auction award complaint {}'.format(self.context.id),
                        extra=context_unpack(self.request, {'MESSAGE_ID': 'auction_award_complaint_patch'}))
            return {'data': self.context.serialize("view")}
