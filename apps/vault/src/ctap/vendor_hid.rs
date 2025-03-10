// Copyright 2022 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use crate::clock::Instant;
use crate::ctap::hid::{
    CtapHid, CtapHidCommand, CtapHidError, HidPacket, HidPacketIterator, Message,
};
use crate::ctap::{Channel, CtapState};
use crate::env::Env;

/// Implements the non-standard command processing for HID.
///
/// Outside of the pure HID commands like INIT, only PING and CBOR commands are allowed.
pub struct VendorHid {
    hid: CtapHid,
}

impl VendorHid {
    /// Instantiates a HID handler for CTAP1, CTAP2 and Wink.
    pub fn new() -> Self {
        let hid = CtapHid::new(CtapHid::CAPABILITY_CBOR | CtapHid::CAPABILITY_NMSG);
        VendorHid { hid }
    }

    /// Processes an incoming USB HID packet, and returns an iterator for all outgoing packets.
    pub fn process_hid_packet(
        &mut self,
        env: &mut impl Env,
        packet: &HidPacket,
        now: Instant,
        ctap_state: &mut CtapState,
    ) -> HidPacketIterator {
        if let Some(message) = self.hid.parse_packet(env, packet, now) {
            let processed_message = self.process_message(env, message, now, ctap_state);
            debug_ctap!(
                env,
                "Sending message through the second usage page: {:02x?}",
                processed_message
            );
            CtapHid::split_message(processed_message)
        } else {
            HidPacketIterator::none()
        }
    }

    /// Processes a message's commands that affect the protocol outside HID.
    pub fn process_message(
        &mut self,
        env: &mut impl Env,
        message: Message,
        now: Instant,
        ctap_state: &mut CtapState,
    ) -> Message {
        let cid = message.cid;
        match message.cmd {
            // There are no custom CTAP1 commands.
            CtapHidCommand::Msg => CtapHid::error_message(cid, CtapHidError::InvalidCmd),
            // The CTAP2 processing function multiplexes internally.
            CtapHidCommand::Cbor => {
                let response =
                    ctap_state.process_command(env, &message.payload, Channel::VendorHid(cid), now);
                Message {
                    cid,
                    cmd: CtapHidCommand::Cbor,
                    payload: response,
                }
            }
            // Call Wink over the main HID.
            CtapHidCommand::Wink => CtapHid::error_message(cid, CtapHidError::InvalidCmd),
            // All other commands have already been processed, keep them as is.
            _ => message,
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::ctap::hid::ChannelID;
    use crate::env::test::TestEnv;

    fn new_initialized() -> (VendorHid, ChannelID) {
        let (hid, cid) = CtapHid::new_initialized();
        (VendorHid { hid }, cid)
    }

    #[test]
    fn test_process_hid_packet() {
        let mut env = TestEnv::new();
        let mut ctap_state = CtapState::new(&mut env, Instant::new(0));
        let (mut vendor_hid, cid) = new_initialized();

        let mut ping_packet = [0x00; 64];
        ping_packet[..4].copy_from_slice(&cid);
        ping_packet[4..9].copy_from_slice(&[0x81, 0x00, 0x02, 0x99, 0x99]);

        let mut response = vendor_hid.process_hid_packet(
            &mut env,
            &ping_packet,
            Instant::new(0),
            &mut ctap_state,
        );
        assert_eq!(response.next(), Some(ping_packet));
        assert_eq!(response.next(), None);
    }

    #[test]
    fn test_process_hid_packet_empty() {
        let mut env = TestEnv::new();
        let mut ctap_state = CtapState::new(&mut env, Instant::new(0));
        let (mut vendor_hid, cid) = new_initialized();

        let mut cancel_packet = [0x00; 64];
        cancel_packet[..4].copy_from_slice(&cid);
        cancel_packet[4..7].copy_from_slice(&[0x91, 0x00, 0x00]);

        let mut response = vendor_hid.process_hid_packet(
            &mut env,
            &cancel_packet,
            Instant::new(0),
            &mut ctap_state,
        );
        assert_eq!(response.next(), None);
    }

    #[test]
    fn test_blocked_commands() {
        let mut env = TestEnv::new();
        let mut ctap_state = CtapState::new(&mut env, Instant::new(0));
        let (mut vendor_hid, cid) = new_initialized();

        // Usually longer, but we don't parse them anyway.
        let mut msg_packet = [0x00; 64];
        msg_packet[..4].copy_from_slice(&cid);
        msg_packet[4..7].copy_from_slice(&[0x83, 0x00, 0x00]);

        let mut wink_packet = [0x00; 64];
        wink_packet[..4].copy_from_slice(&cid);
        wink_packet[4..7].copy_from_slice(&[0x88, 0x00, 0x00]);

        let mut error_packet = [0x00; 64];
        error_packet[..4].copy_from_slice(&cid);
        error_packet[4..8].copy_from_slice(&[0xBF, 0x00, 0x01, 0x01]);

        let mut response = vendor_hid.process_hid_packet(
            &mut env,
            &msg_packet,
            Instant::new(0),
            &mut ctap_state,
        );
        assert_eq!(response.next(), Some(error_packet));
        assert_eq!(response.next(), None);

        let mut response = vendor_hid.process_hid_packet(
            &mut env,
            &wink_packet,
            Instant::new(0),
            &mut ctap_state,
        );
        assert_eq!(response.next(), Some(error_packet));
        assert_eq!(response.next(), None);
    }
}
